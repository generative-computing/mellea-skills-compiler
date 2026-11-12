import os
from typing import Any, Dict, Optional

from mellea_skills_compiler.enums import (
    InferenceEngineType,
    InferenceModel,
    InferenceModelType,
)


OLLAMA_API_URL: Optional[str] = os.environ.get(
    "OLLAMA_API_URL", "http://localhost:11434"
)
VLLM_API_URL_RISK_MODEL: Optional[str] = os.environ.get("VLLM_API_URL_RISK_MODEL", None)
VLLM_API_URL_GUARDIAN_MODEL: Optional[str] = os.environ.get(
    "VLLM_API_URL_GUARDIAN_MODEL", None
)
VLLM_API_KEY_RISK_MODEL: Optional[str] = os.environ.get("VLLM_API_KEY_RISK_MODEL", None)
VLLM_API_KEY_GUARDIAN_MODEL: Optional[str] = os.environ.get(
    "VLLM_API_KEY_GUARDIAN_MODEL", None
)

INFERENCE_ENGINE_CACHE: Dict[tuple, Any] = {}


class InferenceService:

    def __init__(
        self, inference_engine_type: Optional[InferenceEngineType] = None
    ) -> None:
        self.inference_engine_type = (
            inference_engine_type
            if inference_engine_type
            else InferenceEngineType.OLLAMA
        )

    @classmethod
    def risk_engine(
        cls,
        model_name_or_path: Optional[str] = None,
        inference_engine_type: Optional[InferenceEngineType] = None,
    ):

        service: InferenceService = InferenceService(inference_engine_type)
        return InferenceService(inference_engine_type).risk(
            model_name_or_path,
            parameters=(
                # Ollama requires num_ctx to be set explicitly per request to control the
                # context window size. vLLM does not need it here because the context length
                # is configured once at serve time via --max-model-len.
                {"temperature": 0, "num_ctx": 16384}
                if service.inference_engine_type == InferenceEngineType.OLLAMA
                else {"temperature": 0}
            ),
        )

    @classmethod
    def guardian_engine(
        cls,
        model_name_or_path: Optional[str] = None,
        inference_engine_type: Optional[InferenceEngineType] = None,
    ):
        service: InferenceService = InferenceService(inference_engine_type)
        return service.guardian(
            model_name_or_path,
            parameters=(
                # Ollama requires num_ctx to be set explicitly per request to control the
                # context window size. vLLM does not need it here because the context length
                # is configured once at serve time via --max-model-len.
                {"temperature": 0, "num_ctx": 8192, "num_predict": 1024, "think": False}
                if service.inference_engine_type == InferenceEngineType.OLLAMA
                else {"temperature": 0, "max_tokens": 1024}
            ),
        )

    @property
    def inference_engine_class(self):
        from ai_atlas_nexus.blocks.inference import (
            OllamaInferenceEngine,
            VLLMInferenceEngine,
        )

        if self.inference_engine_type == InferenceEngineType.OLLAMA:
            return OllamaInferenceEngine
        if self.inference_engine_type == InferenceEngineType.VLLM:
            return VLLMInferenceEngine
        else:
            raise ValueError(f"Invalid inference engine: {self.inference_engine_type}")

    def credentials(self, model_type: InferenceModelType) -> Optional[Dict[str, Any]]:
        if self.inference_engine_type == InferenceEngineType.OLLAMA:
            return {"api_url": OLLAMA_API_URL}
        elif self.inference_engine_type == InferenceEngineType.VLLM:
            api_url, api_key = (
                (VLLM_API_URL_RISK_MODEL, VLLM_API_KEY_RISK_MODEL)
                if model_type == InferenceModelType.RISK_MODEL
                else (VLLM_API_URL_GUARDIAN_MODEL, VLLM_API_KEY_GUARDIAN_MODEL)
            )
            return {"api_url": api_url, "api_key": api_key} if api_url else None
        else:
            raise ValueError(f"Invalid inference engine: {self.inference_engine_type}")

    def risk(
        self,
        model_name_or_path: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        return self._cache_and_get_inference_engine(
            model_name_or_path=model_name_or_path
            or InferenceModel[f"{self.inference_engine_type.name}_RISK_MODEL"],
            parameters=parameters,
            model_type=InferenceModelType.RISK_MODEL,
        )

    def guardian(
        self,
        model_name_or_path: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        return self._cache_and_get_inference_engine(
            model_name_or_path=model_name_or_path
            or InferenceModel[f"{self.inference_engine_type.name}_GUARDIAN_MODEL"],
            parameters=parameters,
            model_type=InferenceModelType.GUARDIAN_MODEL,
        )

    def _cache_and_get_inference_engine(
        self,
        model_name_or_path: str,
        parameters: Optional[Dict[str, Any]] = None,
        model_type: InferenceModelType = InferenceModelType.RISK_MODEL,
    ):
        parameters = dict(sorted((parameters or {}).items()))
        cache_key = (
            self.inference_engine_type,
            model_name_or_path,
            tuple(parameters.items()),
            model_type,
        )
        if cache_key not in INFERENCE_ENGINE_CACHE:
            INFERENCE_ENGINE_CACHE[cache_key] = self.inference_engine_class(
                model_name_or_path=model_name_or_path,
                credentials=self.credentials(model_type),
                parameters=parameters or {},  # type: ignore[arg-type]
            )
        return INFERENCE_ENGINE_CACHE[cache_key]
