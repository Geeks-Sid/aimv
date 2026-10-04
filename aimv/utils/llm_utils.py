"""
LLM interaction utilities for AIMV.
"""

import re
import time
import json
import base64
import xml.etree.ElementTree as ET
from typing import Optional, Any, Dict, List
from urllib.parse import urlparse
from urllib.request import Request, urlopen
try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional at runtime for Google native calls
    OpenAI = None

from aimv.utils.api_usage import APIUsageTracker, APILimitExceeded, get_tracker


class LLMHelper:
    """Helper class for interacting with LLM APIs."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        max_retries: int = 2,
        retry_delay: int = 2,
        usage_tracker: Optional[APIUsageTracker] = None,
    ):
        """
        Initialize the LLM helper.

        Args:
            api_key (str): API key for the LLM service.
            base_url (str): Base URL for the API.
            model_name (str): Name of the model to use.
            max_retries (int): Maximum number of retries for API calls.
            retry_delay (int): Delay between retries in seconds.
            usage_tracker: Optional APIUsageTracker to enforce daily call limits.
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.current_context = ""
        self.usage_tracker = usage_tracker
        self.client = None
        if not self._uses_google_generate_content():
            if OpenAI is None:
                raise RuntimeError(
                    "openai package is required for non-Google providers. "
                    "Install it or configure OPENAI_API_BASE_URL to Google Generative Language."
                )
            self.client = OpenAI(api_key=api_key, base_url=base_url)

    def _uses_google_generate_content(self) -> bool:
        """Return True when configured for Google Generative Language API."""
        parsed = urlparse(self.base_url or "")
        host = (parsed.netloc or "").lower()
        return "generativelanguage.googleapis.com" in host

    def _supports_json_mode(self) -> bool:
        """Return True if the model supports API-level JSON output enforcement.

        Only Gemini models support responseMimeType / response_format reliably.
        Gemma and other open models ignore or mishandle these params.
        """
        name = (self.model_name or "").lower()
        return name.startswith("gemini") or name.startswith("gpt-")

    def _uses_openai_responses(self) -> bool:
        parsed = urlparse(self.base_url or "")
        return parsed.netloc.lower() == "api.openai.com"

    def _convert_openai_messages_to_google_contents(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Map OpenAI-style messages to Google generateContent payload."""
        contents: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            raw_content = msg.get("content", "")
            google_role = "model" if role == "assistant" else "user"
            parts: List[Dict[str, Any]] = []

            if isinstance(raw_content, list):
                for part in raw_content:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type")
                    if ptype == "text" and part.get("text"):
                        parts.append({"text": part["text"]})
                    elif ptype == "image_url":
                        url = (part.get("image_url") or {}).get("url", "")
                        if url.startswith("data:") and ";base64," in url:
                            header, encoded = url.split(";base64,", 1)
                            mime = header.split(":", 1)[1] if ":" in header else "image/jpeg"
                            try:
                                base64.b64decode(encoded, validate=True)
                                parts.append(
                                    {
                                        "inlineData": {
                                            "mimeType": mime,
                                            "data": encoded,
                                        }
                                    }
                                )
                            except Exception:
                                continue
            else:
                text = str(raw_content).strip()
                if text:
                    parts.append({"text": text})

            if parts:
                contents.append({"role": google_role, "parts": parts})

        return contents

    @staticmethod
    def _convert_messages_to_responses_input(
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert Chat Completions content parts to Responses input parts."""
        converted: List[Dict[str, Any]] = []
        for message in messages:
            raw_content = message.get("content", "")
            if not isinstance(raw_content, list):
                converted.append(
                    {"role": message.get("role", "user"), "content": str(raw_content)}
                )
                continue
            parts: List[Dict[str, Any]] = []
            for part in raw_content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    parts.append({"type": "input_text", "text": part.get("text", "")})
                elif part.get("type") == "image_url":
                    image_url = (part.get("image_url") or {}).get("url")
                    if image_url:
                        parts.append({"type": "input_image", "image_url": image_url})
            converted.append(
                {"role": message.get("role", "user"), "content": parts}
            )
        return converted

    def _call_google_generate_content(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> Optional[str]:
        """Call Google Generative Language API directly using generateContent."""
        base_url = (self.base_url or "").rstrip("/")
        endpoint = f"{base_url}/models/{self.model_name}:generateContent?key={self.api_key}"
        gen_config: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode and self._supports_json_mode():
            gen_config["responseMimeType"] = "application/json"
        payload = {
            "contents": self._convert_openai_messages_to_google_contents(messages),
            "generationConfig": gen_config,
        }

        req = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text_segments = [p.get("text", "") for p in parts if isinstance(p, dict)]
        output = "\n".join([segment for segment in text_segments if segment]).strip()
        return output or None

    def update_context(self, new_info: str, is_user_hint: bool = False) -> None:
        """
        Update the current context for the LLM.

        Args:
            new_info (str): New information to add to the context.
            is_user_hint (bool): Whether the new info is a user hint.
        """
        if new_info:
            prefix = (
                "User's refinement hint: "
                if is_user_hint
                else "Key context from prior step: "
            )
            self.current_context = f"{prefix}{new_info}"

    def call_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1000,
        json_mode: bool = False,
        json_schema: Optional[dict] = None,
    ) -> Optional[str]:
        """
        Call the LLM API.

        Args:
            messages: Messages to send to the API.
            temperature: Temperature parameter for generation.
            max_tokens: Maximum tokens to generate.
            json_mode: Request structured JSON output from the API.

        Returns:
            The content of the LLM response, or None if an error occurred.
        """
        claimed_count = None
        if self.usage_tracker:
            try:
                claimed_count = self.usage_tracker.claim_call()
            except APILimitExceeded as e:
                print(f"\n!!! API LIMIT: {e}")
                return None

        print("\n>>> Calling LLM...")
        try:
            if self._uses_google_generate_content():
                content = self._call_google_generate_content(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
                if not content:
                    print("Error calling LLM: Empty response from Google API")
                    return None
            elif (
                json_schema
                and self._uses_openai_responses()
                and self.client is not None
                and hasattr(self.client, "responses")
            ):
                if self.client is None:
                    raise RuntimeError("OpenAI client is not initialized for this provider.")
                response = self.client.responses.create(
                    model=self.model_name,
                    input=self._convert_messages_to_responses_input(messages),
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    store=False,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "aimv_classification_decision",
                            "strict": True,
                            "schema": json_schema,
                        }
                    },
                )
                content = response.output_text.strip()
            else:
                if self.client is None:
                    raise RuntimeError("OpenAI client is not initialized for this provider.")
                kwargs: Dict[str, Any] = dict(
                    model=self.model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if json_schema and self._supports_json_mode():
                    kwargs["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "aimv_classification_decision",
                            "strict": True,
                            "schema": json_schema,
                        },
                    }
                elif json_mode and self._supports_json_mode():
                    kwargs["response_format"] = {"type": "json_object"}
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content.strip()
            if self.usage_tracker:
                count = claimed_count or self.usage_tracker.calls_today()
                remaining = self.usage_tracker.remaining_today()
                print(f"[API usage: {count} today, {remaining} remaining]")

            print(f"LLM Raw Response (first 300 chars):\n{content[:300]}...\n")
            return content
        except Exception as e:
            print(f"Error calling LLM: {e}")
            return None

    # ------------------------------------------------------------------
    # JSON response helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Extract a JSON object from raw LLM text, stripping fences/prose."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            ).strip()
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    def call_llm_json(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: int = 800,
        json_schema: Optional[dict] = None,
    ) -> Optional[dict]:
        """Call LLM with JSON mode enabled and return a parsed dict.

        Retries on parse failure by appending a correction hint.
        """
        current_messages = list(messages)
        for attempt in range(self.max_retries + 1):
            raw = self.call_llm(
                current_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
                json_schema=json_schema,
            )
            if raw is None:
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                continue

            parsed = self._extract_json(raw)
            if parsed is not None:
                return parsed

            if attempt < self.max_retries:
                current_messages = list(messages) + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            'Respond with ONLY the JSON object. Example format:\n'
                            '{"action":"move","dst":"/path/to/folder","name":"file.pdf",'
                            '"sub":null,"tags":["kw1","kw2"],"conf":0.9}'
                        ),
                    },
                ]
                time.sleep(self.retry_delay)

        print("Failed to get valid JSON after all retries.")
        return None

    # ------------------------------------------------------------------
    # Legacy XML response helpers
    # ------------------------------------------------------------------

    def parse_xml_string(
        self, xml_string: Optional[str], expected_root_tag: Optional[str] = None
    ) -> Optional[ET.Element]:
        """
        Parse XML string from LLM response.

        Args:
            xml_string (Optional[str]): XML string to parse.
            expected_root_tag (Optional[str]): Expected root tag of the XML.

        Returns:
            Optional[ET.Element]: Parsed XML element, or None if parsing failed.
        """
        if xml_string is None:
            print("Error: XML string is None, cannot parse.")
            return None
        if not xml_string.strip():
            print("Error: XML string is empty or whitespace, cannot parse.")
            return None

        try:
            cleaned_xml_string = xml_string
            if cleaned_xml_string.startswith("```xml"):
                cleaned_xml_string = cleaned_xml_string[len("```xml") :]
            elif cleaned_xml_string.startswith("```"):
                cleaned_xml_string = cleaned_xml_string[len("```") :]
            if cleaned_xml_string.endswith("```"):
                cleaned_xml_string = cleaned_xml_string[: -len("```")]
            cleaned_xml_string = cleaned_xml_string.strip()

            cleaned_xml_string = re.sub(r"\s+", " ", cleaned_xml_string).strip()

            # Filter out invalid XML characters
            temp_string_builder = []
            for char_val in cleaned_xml_string:
                cp = ord(char_val)
                if (
                    cp == 0x9
                    or cp == 0xA
                    or cp == 0xD
                    or (0x20 <= cp <= 0xD7FF)
                    or (0xE000 <= cp <= 0xFFFD)
                    or (0x10000 <= cp <= 0x10FFFF)
                ):
                    temp_string_builder.append(char_val)
            cleaned_xml_string = "".join(temp_string_builder)

            if not cleaned_xml_string:
                print("Error: XML string became empty after cleaning.")
                return None

            # Extract XML if it's embedded in other text
            if not cleaned_xml_string.startswith(
                "<"
            ) or not cleaned_xml_string.endswith(">"):
                print(f"Warning: Cleaned XML string may contain extraneous text.")
                start_tag = "<"
                end_tag = ">"

                actual_start_tag = (
                    f"<{expected_root_tag}" if expected_root_tag else start_tag
                )
                start_index = cleaned_xml_string.find(actual_start_tag)

                actual_end_tag = (
                    f"</{expected_root_tag}>" if expected_root_tag else None
                )
                end_index = -1

                if actual_end_tag and start_index != -1:
                    end_index = cleaned_xml_string.find(
                        actual_end_tag, start_index
                    ) + len(actual_end_tag)

                if start_index != -1 and end_index != -1 and start_index < end_index:
                    cleaned_xml_string = cleaned_xml_string[start_index:end_index]

            root = ET.fromstring(cleaned_xml_string)
            if expected_root_tag and root.tag != expected_root_tag:
                print(
                    f"Warning: Expected root tag '{expected_root_tag}', but found '{root.tag}'"
                )
            return root

        except ET.ParseError as e:
            print(
                f"Error parsing XML: {e}\nAttempted to parse (after cleaning):\n{cleaned_xml_string[:500]}..."
            )
            return None
        except Exception as e:
            print(f"An unexpected error occurred during XML parsing: {e}")
            return None

    def call_llm_and_parse_xml(
        self,
        messages: List[Dict[str, str]],
        expected_root_tag: str,
        max_tokens: int = 1000,
        step_name: str = "Unknown Step",
    ) -> Optional[ET.Element]:
        """
        Call LLM API and parse XML response with retry logic.

        Args:
            messages (List[Dict[str, str]]): Messages to send to the API.
            expected_root_tag (str): Expected root tag of the response XML.
            max_tokens (int): Maximum tokens to generate.
            step_name (str): Name of the step for logging purposes.

        Returns:
            Optional[ET.Element]: Parsed XML element, or None if parsing failed after all retries.
        """
        for attempt in range(self.max_retries + 1):
            current_messages = list(messages)
            if attempt > 0:
                # Add retry hint if not the first attempt
                retry_message = {
                    "role": "user",
                    "content": f"Please try again. Make sure to respond with valid XML with root tag <{expected_root_tag}>. "
                    "Don't use backticks or other formatting, just output the XML directly.",
                }
                current_messages.append(retry_message)

            response_str = self.call_llm(current_messages, max_tokens=max_tokens)
            if response_str is None:
                print(
                    f"LLM call failed for {step_name}, attempt {attempt + 1}/{self.max_retries + 1}"
                )
                continue

            root = self.parse_xml_string(response_str, expected_root_tag)
            if root is not None:
                print(
                    f"Successfully parsed XML for {step_name} on attempt {attempt + 1}"
                )
                return root

            print(
                f"Failed to parse XML for {step_name}, attempt {attempt + 1}/{self.max_retries + 1}"
            )
            if attempt < self.max_retries:
                print(f"Retrying in {self.retry_delay} seconds...")
                time.sleep(self.retry_delay)

        print(f"Failed to parse XML for {step_name} after all retries.")
        return None
