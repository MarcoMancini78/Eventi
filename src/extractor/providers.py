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
    """Google Gemini Flash: multimodale, quota gratuita (06.7, 12.10)."""

    def __init__(self, api_key: str, modello: str = "gemini-2.0-flash"):
        if not api_key:
            raise ValueError("LLM_API_KEY mancante in config/.env per il provider gemini")
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self._genai = genai
        self._modello_nome = modello
        self._modello = genai.GenerativeModel(modello)

    def estrai(self, prompt_sistema: str, prompt_utente: str, immagini: list[bytes] | None = None) -> str:
        parti: list = [f"{prompt_sistema}\n\n{prompt_utente}"]
        if immagini:
            for img_bytes in immagini:
                parti.append({"mime_type": "image/jpeg", "data": img_bytes})

        risposta = self._modello.generate_content(
            parti,
            generation_config={"response_mime_type": "application/json"},
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
