"""Astrazione del fornitore LLM (06.1, 15.1). Cambiare provider = cambiare
LLM_PROVIDER in .env, nessuna modifica al resto della pipeline.

Ogni provider implementa lo stesso contratto: estrai(prompt_sistema,
prompt_utente, immagini) -> testo grezzo JSON. La validazione dello schema
e i controlli di sanità restano fuori (client.py), qui c'è solo la chiamata
di rete al modello.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderLLM(ABC):
    @abstractmethod
    def estrai(self, prompt_sistema: str, prompt_utente: str, immagini: list[bytes] | None = None) -> str:
        """Ritorna il testo grezzo della risposta (atteso: JSON)."""


class GeminiProvider(ProviderLLM):
    """Google Gemini Flash: multimodale, quota gratuita (06.7, 12.10).

    Usa il package `google-genai` (successore di `google-generativeai`,
    deprecato). Il nome del modello non è un numero magico da inseguire ad
    ogni deprecazione: resta configurabile via Config se serve cambiarlo
    senza toccare il codice.
    """

    def __init__(self, api_key: str, modello: str = "gemini-flash-latest"):
        if not api_key:
            raise ValueError("LLM_API_KEY mancante in config/.env per il provider gemini")
        from google import genai
        from google.genai import types

        self._client = genai.Client(api_key=api_key)
        self._types = types
        self._modello_nome = modello

    def estrai(self, prompt_sistema: str, prompt_utente: str, immagini: list[bytes] | None = None) -> str:
        from .schema import RispostaEstrazione

        parti: list = [prompt_utente]
        if immagini:
            for img_bytes in immagini:
                parti.append(self._types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))

        # response_schema vincola la forma esatta dell'output (06.2: "se il
        # provider supporta l'output JSON vincolato a schema, va usato").
        # Senza questo il modello può rispondere con una forma diversa da
        # quella attesa (es. un array nudo invece di {"eventi": [...]})
        # anche con response_mime_type="application/json", che garantisce
        # solo JSON sintatticamente valido, non la forma.
        risposta = self._client.models.generate_content(
            model=self._modello_nome,
            contents=parti,
            config=self._types.GenerateContentConfig(
                system_instruction=prompt_sistema,
                response_mime_type="application/json",
                response_schema=RispostaEstrazione,
            ),
        )
        return risposta.text


class AnthropicProvider(ProviderLLM):
    """Claude: stesso contratto, per quando si vorrà cambiare provider."""

    def __init__(self, api_key: str, modello: str = "claude-sonnet-5"):
        if not api_key:
            raise ValueError("LLM_API_KEY mancante in config/.env per il provider anthropic")
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._modello = modello

    def estrai(self, prompt_sistema: str, prompt_utente: str, immagini: list[bytes] | None = None) -> str:
        import base64

        contenuto: list[dict] = [{"type": "text", "text": prompt_utente}]
        if immagini:
            for img_bytes in immagini:
                contenuto.insert(
                    0,
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.b64encode(img_bytes).decode("ascii"),
                        },
                    },
                )

        risposta = self._client.messages.create(
            model=self._modello,
            max_tokens=4096,
            system=prompt_sistema,
            messages=[{"role": "user", "content": contenuto}],
        )
        return risposta.content[0].text


class OpenAIProvider(ProviderLLM):
    """ChatGPT: stesso contratto, per quando si vorrà cambiare provider."""

    def __init__(self, api_key: str, modello: str = "gpt-4o-mini"):
        if not api_key:
            raise ValueError("LLM_API_KEY mancante in config/.env per il provider openai")
        import openai

        self._client = openai.OpenAI(api_key=api_key)
        self._modello = modello

    def estrai(self, prompt_sistema: str, prompt_utente: str, immagini: list[bytes] | None = None) -> str:
        import base64

        contenuto: list[dict] = [{"type": "text", "text": prompt_utente}]
        if immagini:
            for img_bytes in immagini:
                b64 = base64.b64encode(img_bytes).decode("ascii")
                contenuto.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

        risposta = self._client.chat.completions.create(
            model=self._modello,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": contenuto},
            ],
        )
        return risposta.choices[0].message.content


_PROVIDER_PER_NOME = {
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def crea_provider(nome: str, api_key: str) -> ProviderLLM:
    classe = _PROVIDER_PER_NOME.get(nome.lower())
    if classe is None:
        raise ValueError(f"Provider LLM sconosciuto: {nome!r}. Validi: {list(_PROVIDER_PER_NOME)}")
    return classe(api_key)
