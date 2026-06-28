import warnings

warnings.filterwarnings("ignore")

import yaml
import logging
import os
import json
import base64
import time
from typing import Optional, Dict, Any, List
import requests
import io

logger = logging.getLogger(__name__)


def _decode_jwt_exp(token: str) -> Optional[float]:
    """Return the 'exp' Unix timestamp from a JWT payload, or None on failure."""
    try:
        payload_b64 = token.split(".")[1]
        # JWT base64 is URL-safe and may lack padding
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload["exp"])
    except Exception:
        return None


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


class VertexAIEmbeddingClient:
    # Refresh the token this many seconds before it actually expires.
    _TOKEN_REFRESH_BUFFER = 60

    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("embedding", {})
        self.auth_config = config.get("auth", {})
        self.api_url = self.config.get("api_url", "")
        self.model = self.config.get("model", "text-embeddings-004")
        self.task_type = self.config.get("task_type", "SEMANTIC_SIMILARITY")
        self.ssl_verify = self.config.get("ssl_verify", False)
        self._bearer_token: Optional[str] = None
        self._token_exp: Optional[float] = None  # Unix timestamp when token expires

    _TOKEN_CACHE_FILE = ".token_cache.json"

    def _token_is_valid(self) -> bool:
        if self._bearer_token is None:
            return False
        if self._token_exp is None:
            return False
        return time.time() < (self._token_exp - self._TOKEN_REFRESH_BUFFER)

    def _load_cached_token(self):
        try:
            if os.path.exists(self._TOKEN_CACHE_FILE):
                with open(self._TOKEN_CACHE_FILE) as f:
                    data = json.load(f)
                token = data.get("id_token")
                exp = data.get("exp")
                if (
                    token
                    and exp
                    and time.time() < (float(exp) - self._TOKEN_REFRESH_BUFFER)
                ):
                    self._bearer_token = token
                    self._token_exp = float(exp)
                    logger.info("Auth token loaded from cache")
        except Exception:
            pass

    def _save_cached_token(self):
        try:
            with open(self._TOKEN_CACHE_FILE, "w") as f:
                json.dump({"id_token": self._bearer_token, "exp": self._token_exp}, f)
        except Exception:
            pass

    def _fetch_token(self) -> str:
        """Call the auth endpoint and return the id_token from the response."""
        auth_url = self.auth_config.get("auth_url", "")
        ssl_verify = self.auth_config.get("ssl_verify", False)
        if not auth_url:
            raise ValueError("auth.auth_url is not configured in config.yaml")

        try:
            response = requests.post(
                auth_url,
                json={
                    "userid": self.auth_config.get("userid"),
                    "password": self.auth_config.get("password"),
                    "otp": self.auth_config.get("otp"),
                    "otp_type": self.auth_config.get("otp_type"),
                },
                timeout=30,
                verify=ssl_verify,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Failed to fetch auth token from {auth_url}: {exc}"
            ) from exc

        data = response.json()
        id_token = data.get("id_token")
        if not id_token:
            raise RuntimeError(
                f"Auth endpoint response did not contain 'id_token'. Keys present: {list(data.keys())}"
            )
        return id_token

    def _get_token(self) -> str:
        if not self._token_is_valid():
            self._load_cached_token()
        if not self._token_is_valid():
            logger.info("Fetching/refreshing embedding auth token")
            self._bearer_token = self._fetch_token()
            exp = _decode_jwt_exp(self._bearer_token)
            if exp is not None:
                self._token_exp = exp
                logger.info("Auth token acquired; expires in %.0fs", exp - time.time())
            else:
                self._token_exp = time.time() + 55 * 60
                logger.warning("Could not decode token expiry; will refresh in 55 min")
            self._save_cached_token()
        return self._bearer_token

    def embed_text(self, text: str) -> List[float]:
        if not self.api_url:
            logger.warning("No embedding API URL configured, returning dummy embedding")
            import hashlib

            hash_val = hashlib.md5(text.encode()).hexdigest()
            return [
                float(int(hash_val[i : i + 2], 16)) / 255.0 for i in range(0, 16, 2)
            ]

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

        payload = {
            "instances": [{"task_type": self.task_type, "content": text}],
        }

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30,
                verify=self.ssl_verify,
            )
            if response.status_code == 200:
                result = response.json()
                return (
                    result.get("predictions", [{}])[0]
                    .get("embeddings", {})
                    .get("values", [])
                )
            else:
                logger.error(
                    f"Embedding API error: {response.status_code} - {response.text}"
                )
                return self._get_dummy_embedding(text)
        except Exception as e:
            logger.error(f"Error calling embedding API: {e}")
            return self._get_dummy_embedding(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_text(text) for text in texts]

    def _get_dummy_embedding(self, text: str) -> List[float]:
        import hashlib

        hash_val = hashlib.md5(text.encode()).hexdigest()
        return [float(int(hash_val[i : i + 2], 16)) / 255.0 for i in range(0, 16, 2)]


class LocalEmbeddingClient:
    """Local sentence-transformers embedding client. Drop-in for VertexAIEmbeddingClient."""

    _model_instance = None  # Class-level singleton — model loaded once per process

    def __init__(self, config: Dict[str, Any]):
        cfg = config.get("embedding", {})
        self.model_name = cfg.get("local_model", "BAAI/bge-large-en-v1.5")
        self.device = cfg.get("device", "cpu")
        self.normalize = cfg.get("normalize_embeddings", True)
        self.fallback_dim = int(config.get("vector_db", {}).get("embedding_dimension", 1024))
        if LocalEmbeddingClient._model_instance is None:
            try:
                from sentence_transformers import SentenceTransformer

                logger.info(f"Loading local embedding model: {self.model_name}")
                LocalEmbeddingClient._model_instance = SentenceTransformer(
                    self.model_name, device=self.device
                )
                dim = LocalEmbeddingClient._model_instance.get_sentence_embedding_dimension()
                logger.info(f"Local embedding model loaded (dim={dim})")
            except Exception as exc:
                logger.warning(
                    "Falling back to deterministic offline embeddings for %s: %s",
                    self.model_name,
                    exc,
                )
                LocalEmbeddingClient._model_instance = None
        self._model = LocalEmbeddingClient._model_instance

    def _get_fallback_embedding(self, text: str) -> List[float]:
        import hashlib

        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [b / 255.0 for b in digest]
        if self.fallback_dim <= len(values):
            return values[: self.fallback_dim]

        repeated: List[float] = []
        while len(repeated) < self.fallback_dim:
            repeated.extend(values)
        return repeated[: self.fallback_dim]

    def embed_text(self, text: str) -> List[float]:
        if self._model is None:
            return self._get_fallback_embedding(text)
        return self._model.encode(
            text, normalize_embeddings=self.normalize, show_progress_bar=False
        ).tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if self._model is None:
            return [self._get_fallback_embedding(text) for text in texts]
        return [
            e.tolist()
            for e in self._model.encode(
                texts,
                normalize_embeddings=self.normalize,
                show_progress_bar=False,
                batch_size=32,
            )
        ]


class ChromaDBVectorStore:
    def __init__(self, config: Dict[str, Any], embedding_client):
        self.config = config
        self.embedding_client = embedding_client

        try:
            import chromadb
        except ImportError:
            logger.error("ChromaDB not installed")
            raise

        persist_dir = config.get("persist_directory", "./chroma_data")
        collection_name = config.get("collection_name", "ichamp_tickets")

        os.makedirs(persist_dir, exist_ok=True)

        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=collection_name, metadata={"description": "iChamp historical tickets"}
        )

        logger.info(
            f"ChromaDB initialized: collection={collection_name}, persist={persist_dir}"
        )

    def add_documents(self, documents: List[Dict[str, Any]], ids: List[str] = None):
        if not documents:
            return

        if ids is None:
            ids = [doc.get("ticket_id", str(i)) for i, doc in enumerate(documents)]

        texts = []
        for doc in documents:
            # Use rich text if new schema fields present; fall back to old schema
            summary = doc.get("summary", doc.get("description", ""))
            incident_details = doc.get("incident_details", "")
            resolution = doc.get("resolution", "")
            text = f"{summary} {incident_details} {resolution}".strip()
            if not text:
                text = f"Job: {doc.get('job_name', '')} Description: {doc.get('description', '')}"
            texts.append(text)

        embeddings = self.embedding_client.embed_documents(texts)

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=[
                {
                    "ticket_id": doc.get("ticket_id", ""),
                    "job_name": doc.get("job_name", ""),
                    "script_name": doc.get("script_name", ""),
                    "resolved_by": doc.get("resolved_by", ""),
                    "resolved_at": doc.get("resolved_at", ""),
                    "failure_type": doc.get("failure_type", "unknown"),
                    "resolution": doc.get("resolution", ""),
                }
                for doc in documents
            ],
        )

        logger.info(f"Added {len(documents)} documents to ChromaDB")

    def search(
        self, query: str, job_name: str = None, script_name: str = None, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        query_embedding = self.embedding_client.embed_text(query)

        where_filter = {}
        if job_name and script_name:
            where_filter = {
                "$or": [{"job_name": job_name}, {"script_name": script_name}]
            }
        elif job_name:
            where_filter = {"job_name": job_name}
        elif script_name:
            where_filter = {"script_name": script_name}

        try:
            if where_filter:
                results = self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    where=where_filter,
                )
            else:
                results = self.collection.query(
                    query_embeddings=[query_embedding], n_results=top_k
                )
        except Exception as e:
            logger.error(f"ChromaDB search error: {e}")
            return []

        output = []
        if results.get("documents") and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                output.append(
                    {
                        "ticket_id": meta.get("ticket_id", ""),
                        "job_name": meta.get("job_name", ""),
                        "script_name": meta.get("script_name", ""),
                        "failure_type": meta.get("failure_type", ""),
                        "description": doc,
                        "resolution": meta.get("resolution", ""),
                        "resolved_by": meta.get("resolved_by", ""),
                        "resolved_at": meta.get("resolved_at", ""),
                        "similarity_score": 1.0
                        - (
                            results["distances"][0][i]
                            if results.get("distances")
                            else 0.0
                        ),
                    }
                )

        return output

    def get_count(self) -> int:
        return self.collection.count()

    def clear(self):
        try:
            self.client.delete_collection(name=self.collection.name)
            self.collection = self.client.get_or_create_collection(
                name=self.config.get("collection_name", "ichamp_tickets"),
                metadata={"description": "iChamp historical tickets"},
            )
            logger.info("ChromaDB collection cleared")
        except Exception as e:
            logger.error(f"Error clearing collection: {e}")


class IChampClient:
    def __init__(self, config: Dict[str, Any]):
        ichamp_config = config.get("ichamp", {})
        self.api_url = ichamp_config.get("api_url", "https://ichamp.dbs.com/api")
        self.client_id = ichamp_config.get("client_id", "")
        self.client_secret = ichamp_config.get("client_secret", "")
        self._access_token = None

    def _get_token(self) -> str:
        if self._access_token is None:
            from ada_genai.auth import sso_auth

            sso_auth.login()
            token_info = sso_auth.get_token()
            self._access_token = token_info.get("access_token", "")
        return self._access_token

    def fetch_tickets(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }

        params = {"start_date": start_date, "end_date": end_date}

        try:
            response = requests.get(
                f"{self.api_url}/tickets/export",
                headers=headers,
                params=params,
                timeout=60,
            )
            if response.status_code == 200:
                return self._parse_excel(response.content)
            else:
                logger.error(
                    f"iChamp API error: {response.status_code} - {response.text}"
                )
                return []
        except Exception as e:
            logger.error(f"Error fetching iChamp tickets: {e}")
            return []

    def _parse_excel(self, content: bytes) -> List[Dict[str, Any]]:
        try:
            import pandas as pd

            df = pd.read_excel(io.BytesIO(content))

            tickets = []
            for _, row in df.iterrows():
                ticket = {
                    "ticket_id": str(row.get("ticket_id", row.get("INCIDENT_ID", ""))),
                    "job_name": str(row.get("job_name", row.get("JOB_NAME", ""))),
                    "script_name": str(
                        row.get("script_name", row.get("SCRIPT_NAME", ""))
                    ),
                    "command": str(row.get("command", row.get("COMMAND", ""))),
                    "summary": str(
                        row.get(
                            "summary", row.get("SUMMARY", row.get("DESCRIPTION", ""))
                        )
                    ),
                    "incident_details": str(
                        row.get(
                            "incident_details",
                            row.get("INCIDENT_DETAILS", row.get("DESCRIPTION", "")),
                        )
                    ),
                    "description": str(
                        row.get("description", row.get("DESCRIPTION", ""))
                    ),
                    "resolution": str(row.get("resolution", row.get("RESOLUTION", ""))),
                    "failure_type": str(
                        row.get("failure_type", row.get("FAILURE_TYPE", "unknown"))
                    ),
                    "resolved_by": str(
                        row.get("resolved_by", row.get("RESOLVED_BY", ""))
                    ),
                    "resolved_at": str(
                        row.get("resolved_at", row.get("RESOLVED_DATE", ""))
                    ),
                }
                if ticket["ticket_id"]:
                    tickets.append(ticket)

            logger.info(f"Parsed {len(tickets)} tickets from iChamp Excel")
            return tickets
        except Exception as e:
            logger.error(f"Error parsing Excel: {e}")
            return []


class MCPClientWrapper:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._mcp_config = config.get("mcp", {})

    def _build_server_config(self, key: str) -> Dict[str, Any]:
        cfg = self._mcp_config.get(key, {})
        env = {**cfg.get("env", {}), **os.environ}
        return {
            cfg.get("name", key): {
                "transport": cfg.get("transport", "stdio"),
                "command": cfg.get("command", ""),
                "args": cfg.get("args", []),
                "env": env,
            }
        }

    @property
    def bitbucket_server_config(self) -> Dict[str, Any]:
        return self._build_server_config("bitbucket")

    @property
    def jira_server_config(self) -> Dict[str, Any]:
        return self._build_server_config("jira")


class EdgeNodeClient:
    def __init__(self, node_config: Dict[str, Any]):
        self.name = node_config.get("name", "unknown")
        self.host = node_config.get("host", "localhost")
        self.port = node_config.get("port", 5000)
        self.scripts_path = node_config.get("scripts_path", "/opt/tws/scripts")
        self.logs_path = node_config.get("logs_path", "/var/log/tws")
        self.base_url = f"http://{self.host}:{self.port}"

    def get_script(self, script_name: str) -> Optional[Dict[str, Any]]:
        try:
            response = requests.get(
                f"{self.base_url}/api/script",
                params={"name": script_name, "scripts_path": self.scripts_path},
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()
            logger.warning(
                f"Failed to get script {script_name} from {self.name}: {response.status_code}"
            )
            return None
        except Exception as e:
            logger.error(f"Error connecting to edge node {self.name}: {e}")
            return None

    def get_logs(self, log_name: str, lines: int = 100) -> Optional[Dict[str, Any]]:
        try:
            response = requests.get(
                f"{self.base_url}/api/logs",
                params={"name": log_name, "lines": lines},
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Error getting logs from {self.name}: {e}")
            return None

    def get_env_vars(self) -> Optional[Dict[str, str]]:
        try:
            response = requests.get(f"{self.base_url}/api/env", timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Error getting env vars from {self.name}: {e}")
            return None


class EdgeNodePool:
    def __init__(self, nodes: List[Dict[str, Any]]):
        self.nodes = {node["name"]: EdgeNodeClient(node) for node in nodes}

    def get_node(self, name: str) -> Optional[EdgeNodeClient]:
        return self.nodes.get(name)

    def find_node_by_job(self, job_name: str) -> Optional[EdgeNodeClient]:
        return next(iter(self.nodes.values()), None)


class Tools:
    config: Optional[Dict[str, Any]] = None
    edge_node_pool: Optional[EdgeNodePool] = None
    vector_db: Optional[ChromaDBVectorStore] = None
    mcp_client: Optional[MCPClientWrapper] = None
    embedding_client: Optional[VertexAIEmbeddingClient] = None
    ichamp_client: Optional[IChampClient] = None
    bitbucket_tools: Optional[List[Any]] = None
    jira_tools: Optional[List[Any]] = None

    @classmethod
    def initialize(cls, config: Dict[str, Any]):
        cls.config = config

        edge_nodes_config = config.get("edge_nodes", [])
        cls.edge_node_pool = EdgeNodePool(edge_nodes_config)

        vector_db_config = config.get("vector_db", {})
        if vector_db_config.get("provider") == "chromadb":
            embedding_provider = config.get("embedding", {}).get("provider", "vertexai")
            if embedding_provider == "local":
                cls.embedding_client = LocalEmbeddingClient(config)
            else:
                cls.embedding_client = VertexAIEmbeddingClient(config)
            cls.vector_db = ChromaDBVectorStore(vector_db_config, cls.embedding_client)

        cls.ichamp_client = IChampClient(config)
        cls.mcp_client = MCPClientWrapper(config)

    @classmethod
    async def initialize_mcp_tools(cls):
        from langchain_mcp_adapters.client import MultiServerMCPClient

        try:
            client = MultiServerMCPClient(cls.mcp_client.bitbucket_server_config)
            cls.bitbucket_tools = await client.get_tools()
            logger.info("Bitbucket MCP tools initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Bitbucket MCP tools: {e}")

        try:
            client = MultiServerMCPClient(cls.mcp_client.jira_server_config)
            cls.jira_tools = await client.get_tools()
            logger.info("Jira MCP tools initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Jira MCP tools: {e}")
