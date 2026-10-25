import time
import json
import logging
from typing import Dict, Any, Optional, Tuple, Union
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Exceção base para erros do cliente LLM."""
    pass


class LLMConnectionError(LLMError):
    """Exceção levantada quando o servidor local Ollama está inacessível."""
    pass


class LLMTimeoutError(LLMError):
    """Exceção levantada quando a requisição ao LLM excede o tempo limite."""
    pass


class LLMResponseError(LLMError):
    """Exceção levantada quando o LLM retorna status HTTP de erro ou formato inválido."""
    pass


class LLMClient:
    """
    Gateway de comunicação com o modelo de linguagem (Qwen 2.5) servido localmente via Ollama.
    """

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: int = 3,
        mock_mode: bool = False,
        **kwargs: Any
    ):
        self.endpoint_url = (endpoint_url or settings.LLM_ENDPOINT_URL).rstrip("/")
        self.model_name = model_name or settings.LLM_MODEL
        self.timeout_seconds = timeout_seconds or settings.LLM_TIMEOUT_SECONDS
        self.max_retries = max_retries
        self.mock_mode = mock_mode

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json"
        }

    def _build_payload_and_url(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        top_p: float = 0.9,
        repetition_penalty: float = 1.0,
        format: Optional[Union[str, Dict[str, Any]]] = None,
        seed: Optional[int] = None
    ) -> Tuple[str, Dict[str, Any]]:
        resolved_max_tokens = max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS

        url = f"{self.endpoint_url}/api/generate"
        options: Dict[str, Any] = {
            "num_predict": resolved_max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "repeat_penalty": repetition_penalty,
            "num_ctx": settings.LLM_NUM_CTX
        }
        if seed is not None:
            options["seed"] = int(seed)

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "30m",
            "options": options
        }
        if format:
            payload["format"] = format

        return url, payload

    def health_check(self) -> Dict[str, Any]:
        """
        Executa verificação de disponibilidade no servidor Ollama local (GET /api/tags).
        """
        if self.mock_mode or not self.endpoint_url:
            return {"status": "mock", "healthy": True, "message": "Modo Mock ativo"}

        url = f"{self.endpoint_url}/api/tags"
        start_time = time.time()
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers=self.headers)
                latency_ms = round((time.time() - start_time) * 1000, 2)
                if response.status_code == 200:
                    data = response.json() if response.text and response.headers.get("content-type", "").startswith("application/json") else {}
                    models = [m.get("name") for m in data.get("models", [])]
                    model_available = any(self.model_name in m for m in models) if self.model_name else True
                    return {
                        "status": "healthy",
                        "healthy": True,
                        "provider": "ollama",
                        "model": self.model_name,
                        "model_available": model_available,
                        "latency_ms": latency_ms,
                        "details": data
                    }
                return {
                    "status": "unhealthy",
                    "healthy": False,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "message": f"Servidor Ollama retornou HTTP {response.status_code}"
                }
        except httpx.TimeoutException:
            return {
                "status": "timeout",
                "healthy": False,
                "message": f"Tempo limite de conexão esgotado ao acessar {url}"
            }
        except Exception as e:
            return {
                "status": "error",
                "healthy": False,
                "message": f"Falha de conexão com o servidor Ollama ({e})"
            }

    def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        top_p: float = 0.9,
        repetition_penalty: float = 1.0,
        format: Optional[Union[str, Dict[str, Any]]] = None,
        seed: Optional[int] = None
    ) -> str:
        """Executa chamada síncrona ao LLM com retries e backoff exponencial."""
        if self.mock_mode:
            return self._generate_mock_response(prompt, format=format)

        url, payload = self._build_payload_and_url(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            format=format,
            seed=seed
        )

        last_exception = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(url, json=payload, headers=self.headers)

                    if response.status_code == 200:
                        data = response.json()
                        if "response" in data:
                            return data["response"]
                        raise LLMResponseError(f"Formato de resposta inesperado do Ollama: {data}")

                    if response.status_code in [502, 503, 504]:
                        logger.warning(f"Servidor retornou HTTP {response.status_code} na tentativa {attempt}.")
                    else:
                        raise LLMResponseError(
                            f"Erro retornado pelo LLM (HTTP {response.status_code}): {response.text}"
                        )

            except httpx.TimeoutException as e:
                logger.warning(f"Timeout na tentativa {attempt}/{self.max_retries} ({e})")
                last_exception = LLMTimeoutError(f"Tempo limite de {self.timeout_seconds}s esgotado.")
            except httpx.RequestError as e:
                logger.warning(f"Erro de conexão na tentativa {attempt}/{self.max_retries} ({e})")
                last_exception = LLMConnectionError(f"Falha de comunicação com {url}: {e}")
            except Exception as e:
                last_exception = e

            if attempt < self.max_retries:
                sleep_time = (2 ** (attempt - 1)) * 1.5
                time.sleep(sleep_time)

        if isinstance(last_exception, LLMError):
            raise last_exception
        raise LLMConnectionError(f"Não foi possível obter resposta após {self.max_retries} tentativas: {last_exception}")

    def _generate_mock_response(self, prompt: str, format: Optional[Union[str, Dict[str, Any]]] = None) -> str:
        """
        Gera resposta didática ou estruturada simulada para testes locais instantâneos.
        """
        prompt_lower = prompt.lower()

        if "auditoria binária de critério único" in prompt_lower:
            return json.dumps({"defeito": False, "evidencia": "Critério atendido."}, ensure_ascii=False)

        if "juiz de mapeamento de resposta para alternativa" in prompt_lower:
            return json.dumps({"letras_equivalentes": ["B"], "explicacao": "Resultado corresponde à alternativa B."}, ensure_ascii=False)

        if "juiz de equivalência matemática" in prompt_lower:
            return json.dumps({"equivalentes": True, "explicacao_equivalencia": "Resultados equivalentes comprovados."}, ensure_ascii=False)

        if "resolucao_passo_a_passo" in prompt_lower and "premissas_assumidas" in prompt_lower:
            return json.dumps({
                "resolucao_passo_a_passo": "Taxa líquida de enchimento: 40 - 10 = 30 L/min. Tempo total: 1200 / 30 = 40 minutos.",
                "premissas_assumidas": [],
                "dados_nao_utilizados": [],
                "pergunta_respondivel": True,
                "resultado_obtido": 40
            }, ensure_ascii=False)

        if "etapa 1a — planejamento e enunciado" in prompt_lower:
            return json.dumps({
                "planejamento": "Dados: capacidade 1200 L, entrada 40 L/min, saída 10 L/min. Etapas: (1) taxa líquida 40-10=30; (2) tempo 1200/30=40 min.",
                "enunciado": "Um reservatório com capacidade de 1.200 litros é abastecido a uma taxa constante de 40 litros por minuto, enquanto uma válvula esvazia a 10 litros por minuto. Estando inicialmente vazio, qual é o tempo necessário, em minutos, para enchê-lo completamente?",
                "tabela_dados": None,
                "erros_tipicos": [
                    "Desconsiderar a vazão de saída no cálculo",
                    "Dividir a capacidade apenas pela vazão de saída",
                    "Somar as vazões de entrada e saída em vez de subtrair",
                    "Multiplicar a taxa líquida pela vazão de saída"
                ]
            }, ensure_ascii=False)

        if "escreva exclusivamente a função python `def resolver():`" in prompt_lower:
            return json.dumps({
                "solver": "def resolver():\n    capacidade = 1200\n    volume_inicial = 0\n    entrada = 40\n    saida = 10\n    falta = capacidade - volume_inicial\n    taxa_liquida = entrada - saida\n    correta = falta / taxa_liquida\n    erro_sem_saida = falta / entrada\n    erro_so_saida = falta / saida\n    erro_soma_taxas = falta / (entrada + saida)\n    erro_multiplicou_taxa = (entrada - saida) * saida"
            }, ensure_ascii=False)

        if "solver" in prompt_lower:
            mock_pot = {
                "planejamento": "Dados: capacidade 1200 L, entrada 40 L/min, saída 10 L/min. Etapas: (1) taxa líquida; (2) divisão.",
                "enunciado": "Um reservatório com capacidade de 1.200 litros é abastecido a uma taxa constante de 40 litros por minuto, enquanto uma válvula esvazia a 10 litros por minuto. Estando inicialmente vazio, qual é o tempo necessário, em minutos, para enchê-lo completamente?",
                "tabela_dados": None,
                "erros_tipicos": [
                    "Desconsiderar a vazão de saída no cálculo",
                    "Dividir a capacidade apenas pela vazão de saída",
                    "Somar as vazões de entrada e saída em vez de subtrair",
                    "Multiplicar a taxa líquida pela vazão de saída"
                ],
                "solver": "def resolver():\n    capacidade = 1200\n    volume_inicial = 0\n    entrada = 40\n    saida = 10\n    falta = capacidade - volume_inicial\n    taxa_liquida = entrada - saida\n    correta = falta / taxa_liquida\n    erro_sem_saida = falta / entrada\n    erro_so_saida = falta / saida\n    erro_soma_taxas = falta / (entrada + saida)\n    erro_multiplicou_taxa = (entrada - saida) * saida"
            }
            return json.dumps(mock_pot, ensure_ascii=False)

        return json.dumps({
            "enunciado": "Um reservatório de 1.200 litros é abastecido a 40 L/min e esvaziado a 10 L/min. Em quantos minutos encherá?",
            "alternativas": {"A": "30", "B": "40", "C": "50", "D": "60", "E": "80"},
            "gabarito": "B",
            "justificativa": "Taxa líquida de 30 L/min leva 40 min para 1200 L."
        }, ensure_ascii=False)
