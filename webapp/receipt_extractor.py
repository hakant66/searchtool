from __future__ import annotations

import json
import os
import re
import hashlib
from io import BytesIO
from typing import Any

from pypdf import PdfReader

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

try:
    import fitz  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    fitz = None  # type: ignore[assignment]


class ReceiptExtractionError(Exception):
    pass


def _norm_text(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _token_overlap_score(needle: str, haystack: str) -> float:
    n_tokens = {t for t in _norm_text(needle).split(" ") if len(t) >= 3}
    h_tokens = {t for t in _norm_text(haystack).split(" ") if len(t) >= 3}
    if not n_tokens or not h_tokens:
        return 0.0
    inter = len(n_tokens.intersection(h_tokens))
    if inter == 0:
        return 0.0
    return inter / max(1, len(n_tokens))


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    if not raw_text:
        return {}
    text = raw_text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _openai_extract_with_responses(
    *,
    client: Any,
    model_name: str,
    content_parts: list[dict[str, Any]],
) -> dict[str, Any]:
    response = client.responses.create(
        model=model_name,
        input=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "You are an extraction engine. Return valid JSON only and no markdown.",
                    }
                ],
            },
            {"role": "user", "content": content_parts},
        ],
        max_output_tokens=900,
    )

    raw = getattr(response, "output_text", "") or ""
    if not raw.strip():
        message_parts: list[str] = []
        for item in getattr(response, "output", []):
            if not isinstance(item, dict):
                continue
            for segment in item.get("content", []):
                if segment.get("type") == "output_text" and segment.get("text"):
                    message_parts.append(segment["text"])
        raw = "\n".join(message_parts)
    return _extract_json_object(raw)


def _openai_extract_with_chat_completions(
    *,
    client: Any,
    model_name: str,
    user_text: str,
    image_data_url: str | None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    if image_data_url:
        content.append({"type": "image_url", "image_url": {"url": image_data_url}})

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "Return strict JSON only. No markdown."},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = ""
    if response.choices and response.choices[0].message:
        raw = str(response.choices[0].message.content or "")
    return _extract_json_object(raw)


def _extract_pdf_with_pypdf(pdf_bytes: bytes) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    reader = PdfReader(BytesIO(pdf_bytes))
    text_parts: list[str] = []
    images: list[dict[str, Any]] = []
    text_lines: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for page_index, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            text_parts.append(page_text)
            for line in page_text.splitlines():
                if line.strip():
                    text_lines.append(
                        {
                            "page": page_index,
                            "text": line.strip(),
                            "x0": 0.0,
                            "y0": float(len(text_lines)),
                            "x1": 1000.0,
                            "y1": float(len(text_lines)) + 1.0,
                        }
                    )

        try:
            page_images = getattr(page, "images", [])
            for image in page_images:
                data = getattr(image, "data", None)
                if not data:
                    continue
                blob = bytes(data)
                if not blob:
                    continue
                digest = hashlib.sha1(blob).hexdigest()
                name = str(getattr(image, "name", "")).lower()
                key = f"{page_index}:{name}:{digest}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                mime = "image/jpeg"
                if name.endswith(".png"):
                    mime = "image/png"
                elif name.endswith(".webp"):
                    mime = "image/webp"
                images.append(
                    {
                        "page": page_index,
                        "x0": float(len(images)),
                        "y0": float(len(images)),
                        "x1": float(len(images)) + 1.0,
                        "y1": float(len(images)) + 1.0,
                        "blob": blob,
                        "mime": mime,
                    }
                )
        except Exception:
            pass

    return "\n\n".join(text_parts).strip(), images, text_lines


def _extract_pdf_with_fitz(pdf_bytes: bytes) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if fitz is None:  # pragma: no cover
        return "", [], []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_parts: list[str] = []
    images: list[dict[str, Any]] = []
    text_lines: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        page_text = page.get_text("text") or ""
        if page_text.strip():
            text_parts.append(page_text)

        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                joined = "".join(str(s.get("text", "")) for s in spans).strip()
                if not joined:
                    continue
                bbox = line.get("bbox") or spans[0].get("bbox") or [0, 0, 0, 0]
                text_lines.append(
                    {
                        "page": page_index,
                        "text": joined,
                        "x0": float(bbox[0]),
                        "y0": float(bbox[1]),
                        "x1": float(bbox[2]),
                        "y1": float(bbox[3]),
                    }
                )

        for info in page.get_image_info(xrefs=True):
            xref = int(info.get("xref", 0) or 0)
            if xref <= 0:
                continue
            extracted = doc.extract_image(xref)
            blob = bytes(extracted.get("image") or b"")
            if not blob:
                continue
            ext = str(extracted.get("ext") or "jpg").lower()
            mime = "image/jpeg"
            if ext == "png":
                mime = "image/png"
            elif ext == "webp":
                mime = "image/webp"
            bbox = info.get("bbox") or [0, 0, 0, 0]
            x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            digest = hashlib.sha1(blob).hexdigest()
            key = f"{page_index}:{xref}:{round(x0, 2)}:{round(y0, 2)}:{round(x1, 2)}:{round(y1, 2)}:{digest}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            images.append(
                {
                    "page": page_index,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "blob": blob,
                    "mime": mime,
                }
            )

    return "\n\n".join(text_parts).strip(), images, text_lines


def _extract_pdf_text_and_images(pdf_bytes: bytes) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if fitz is not None:
        text, images, lines = _extract_pdf_with_fitz(pdf_bytes)
        if text.strip():
            images.sort(key=lambda d: (int(d["page"]), float(d["y0"]), float(d["x0"])))
            return text, images, lines
    return _extract_pdf_with_pypdf(pdf_bytes)


def _match_item_images(
    *,
    items: list[dict[str, Any]],
    candidate_images: list[dict[str, Any]],
    text_lines: list[dict[str, Any]],
    fallback_image: bytes | None,
) -> list[bytes | None]:
    if not items:
        return []
    if not candidate_images:
        return [fallback_image for _ in items]

    used: set[int] = set()
    assignments: list[bytes | None] = []

    for item in items:
        item_name = str(item.get("item_name", "") or "")
        anchor: dict[str, Any] | None = None
        best_anchor_score = 0.0
        if item_name:
            for line in text_lines:
                score = _token_overlap_score(item_name, str(line.get("text", "")))
                if score > best_anchor_score:
                    best_anchor_score = score
                    anchor = line

        chosen_index: int | None = None
        chosen_score = 10**9
        for idx, image in enumerate(candidate_images):
            if idx in used:
                continue

            # base order fallback (stable top-to-bottom, left-to-right)
            score = float(idx) * 1000.0
            if anchor is not None and best_anchor_score >= 0.35:
                same_page = 0.0 if int(image["page"]) == int(anchor["page"]) else 10000.0
                img_cy = (float(image["y0"]) + float(image["y1"])) / 2.0
                txt_cy = (float(anchor["y0"]) + float(anchor["y1"])) / 2.0
                vertical_gap = abs(img_cy - txt_cy)
                horizontal_gap = max(0.0, float(anchor["x0"]) - float(image["x1"]))
                right_side_penalty = 300.0 if float(image["x0"]) > float(anchor["x0"]) else 0.0
                score = same_page + vertical_gap + horizontal_gap + right_side_penalty

            if score < chosen_score:
                chosen_score = score
                chosen_index = idx

        if chosen_index is None:
            assignments.append(fallback_image)
            continue

        used.add(chosen_index)
        assignments.append(bytes(candidate_images[chosen_index]["blob"]))

    return assignments


def _normalize_count(raw: Any) -> int:
    if isinstance(raw, int):
        return max(1, raw)
    text = str(raw or "").strip()
    match = re.search(r"(\d+)", text)
    if not match:
        return 1
    try:
        return max(1, int(match.group(1)))
    except ValueError:
        return 1


def _build_openai_receipt_prompt(*, filename: str, extracted_text: str) -> str:
    instruction = (
        "Extract shopping receipt fields and return strict JSON only with this structure: "
        "{marketplace, order_id, order_time, payment_method, items:[{item_name,item_info,item_cost,item_count,item_trader}]}. "
        "Keep values exactly as shown in source when possible. item_count must be numeric if present. "
        "If a field is missing, use empty string; if items are missing, return an empty list."
    )
    if extracted_text.strip():
        return f"Filename: {filename}\n\n{instruction}\n\nPDF text:\n{extracted_text[:24000]}"
    return (
        f"Filename: {filename}\n\n{instruction}\n\n"
        "This PDF has no extractable text layer. Read the receipt from the provided page images."
    )


def _build_openai_content_parts(
    *,
    filename: str,
    extracted_text: str,
    vision_images: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    import base64

    user_text = _build_openai_receipt_prompt(filename=filename, extracted_text=extracted_text)
    content_parts: list[dict[str, Any]] = [{"type": "input_text", "text": user_text}]
    first_image_data_url: str | None = None

    for image in vision_images:
        blob = bytes(image.get("blob") or b"")
        if not blob:
            continue
        encoded = base64.b64encode(blob).decode("ascii")
        image_data_url = f"data:{str(image.get('mime') or 'image/jpeg')};base64,{encoded}"
        if first_image_data_url is None:
            first_image_data_url = image_data_url
        content_parts.append(
            {
                "type": "input_image",
                "image_url": image_data_url,
            }
        )

    return content_parts, first_image_data_url


def _extract_with_openai(
    *,
    client: Any,
    model_name: str,
    prompt_text: str,
    image_data_urls: list[str] | None = None,
) -> dict[str, Any]:
    content_parts: list[dict[str, Any]] = [{"type": "input_text", "text": prompt_text}]
    for image_data_url in image_data_urls or []:
        content_parts.append({"type": "input_image", "image_url": image_data_url})

    parsed: dict[str, Any] = {}
    errors: list[str] = []
    try:
        parsed = _openai_extract_with_responses(
            client=client,
            model_name=model_name,
            content_parts=content_parts,
        )
    except Exception as exc:
        errors.append(f"responses: {exc}")

    if not parsed:
        fallback_image = image_data_urls[0] if image_data_urls else None
        try:
            parsed = _openai_extract_with_chat_completions(
                client=client,
                model_name=model_name,
                user_text=prompt_text,
                image_data_url=fallback_image,
            )
        except Exception as exc:
            errors.append(f"chat.completions: {exc}")

    if parsed:
        return parsed

    detail = f" ({'; '.join(errors)})" if errors else ""
    raise ReceiptExtractionError(f"OpenAI response is not valid JSON{detail}")


def _build_receipt_summary_prompt() -> str:
    return (
        "This image is the order summary page from a shopping receipt. "
        "Return strict JSON only with this structure: "
        "{marketplace, order_id, order_time, payment_method}. "
        "Use the exact values shown. If a field is missing, return an empty string. "
        "Do not return items."
    )


def _build_receipt_items_prompt(*, page_number: int, page_count: int) -> str:
    return (
        f"This image is page {page_number} of {page_count} from a shopping receipt. "
        "Extract each purchased product card visible on this page and return strict JSON only as "
        "{items:[{item_name,item_info,item_cost,item_count,item_trader}]}. "
        "Rules: one object per visible product card; item_name is the full product title; "
        "item_info is the variant/color/style line under the title; item_cost is the price on the right; "
        "item_count is the numeric quantity from markers such as x2 or x3; "
        "item_trader is the seller shown after 'Sold by trader'. "
        "Ignore headers, footers, payment method, subtotal, shipping, coupons, tax, and order summary details. "
        "If no product cards are visible on this page, return an empty items list."
    )


def _image_to_data_url(image: dict[str, Any]) -> str | None:
    import base64

    blob = bytes(image.get("blob") or b"")
    if not blob:
        return None
    mime = str(image.get("mime") or "image/jpeg")
    encoded = base64.b64encode(blob).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _normalize_items_with_page_images(
    *,
    items: list[dict[str, Any]],
    fallback_image: bytes | None,
) -> list[dict[str, Any]]:
    normalized_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_image_bytes = item.get("item_image_bytes")
        normalized_items.append(
            {
                "item_name": str(item.get("item_name", "") or ""),
                "item_info": str(item.get("item_info", "") or ""),
                "item_cost": str(item.get("item_cost", "") or ""),
                "item_count": _normalize_count(item.get("item_count", 1)),
                "item_trader": str(item.get("item_trader", "") or ""),
                "item_image_bytes": bytes(item_image_bytes)
                if isinstance(item_image_bytes, (bytes, bytearray))
                else fallback_image,
            }
        )
    return normalized_items


def _extract_receipt_from_image_pages(
    *,
    client: Any,
    model_name: str,
    filename: str,
    raw_images: list[dict[str, Any]],
) -> dict[str, Any]:
    first_image_bytes = bytes(raw_images[0]["blob"]) if raw_images else None
    summary_page = raw_images[0] if raw_images else None
    summary_data_url = _image_to_data_url(summary_page) if summary_page else None
    summary = (
        _extract_with_openai(
            client=client,
            model_name=model_name,
            prompt_text=f"Filename: {filename}\n\n{_build_receipt_summary_prompt()}",
            image_data_urls=[summary_data_url] if summary_data_url else [],
        )
        if summary_data_url
        else {}
    )

    extracted_items: list[dict[str, Any]] = []
    page_count = len(raw_images)
    for page_number, image in enumerate(raw_images, start=1):
        image_data_url = _image_to_data_url(image)
        if not image_data_url:
            continue
        page_result = _extract_with_openai(
            client=client,
            model_name=model_name,
            prompt_text=f"Filename: {filename}\n\n{_build_receipt_items_prompt(page_number=page_number, page_count=page_count)}",
            image_data_urls=[image_data_url],
        )
        for item in page_result.get("items") if isinstance(page_result.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            item_copy = dict(item)
            item_copy["item_image_bytes"] = bytes(image["blob"])
            extracted_items.append(item_copy)

    return {
        "marketplace": str(summary.get("marketplace", "") or ""),
        "order_id": str(summary.get("order_id", "") or ""),
        "order_time": str(summary.get("order_time", "") or ""),
        "payment_method": str(summary.get("payment_method", "") or ""),
        "items": _normalize_items_with_page_images(items=extracted_items, fallback_image=first_image_bytes),
        "first_image_bytes": first_image_bytes,
    }


def extract_receipt_fields_with_openai(
    *,
    pdf_bytes: bytes,
    filename: str,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    key = str(api_key or os.getenv("OPENAI_API_KEY", "")).strip()
    if not key:
        raise ReceiptExtractionError("OPENAI_API_KEY is required for receipt extraction")
    if OpenAI is None:
        raise ReceiptExtractionError("openai package is not installed")

    extracted_text, raw_images, text_lines = _extract_pdf_text_and_images(pdf_bytes)
    if not extracted_text and not raw_images:
        raise ReceiptExtractionError("No extractable text found in the PDF")

    min_item_image_bytes = int(os.getenv("RECEIPT_MIN_ITEM_IMAGE_BYTES", "6000"))
    candidate_images = [img for img in raw_images if len(bytes(img["blob"])) >= min_item_image_bytes]
    if not candidate_images and raw_images:
        candidate_images = raw_images
    first_image_bytes = bytes(candidate_images[0]["blob"]) if candidate_images else None
    client = OpenAI(api_key=key, timeout=90, max_retries=1)
    model_name = model or os.getenv("RECEIPT_OPENAI_MODEL", "gpt-4.1-mini")
    if not extracted_text.strip() and candidate_images:
        return _extract_receipt_from_image_pages(
            client=client,
            model_name=model_name,
            filename=filename,
            raw_images=candidate_images,
        )

    vision_images = candidate_images[:6]
    content_parts, image_data_url = _build_openai_content_parts(
        filename=filename,
        extracted_text=extracted_text,
        vision_images=vision_images,
    )
    user_text = _build_openai_receipt_prompt(filename=filename, extracted_text=extracted_text)
    parsed = _extract_with_openai(
        client=client,
        model_name=model_name,
        prompt_text=user_text,
        image_data_urls=[image_data_url] if image_data_url else [],
    )

    items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
    dict_items = [x for x in items if isinstance(x, dict)]
    image_assignments = _match_item_images(
        items=dict_items,
        candidate_images=candidate_images,
        text_lines=text_lines,
        fallback_image=first_image_bytes,
    )
    normalized_items: list[dict[str, Any]] = []
    image_idx = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        item_copy = dict(item)
        item_copy["item_image_bytes"] = (
            image_assignments[image_idx] if image_idx < len(image_assignments) else first_image_bytes
        )
        image_idx += 1
        normalized_items.extend(_normalize_items_with_page_images(items=[item_copy], fallback_image=first_image_bytes))

    return {
        "marketplace": str(parsed.get("marketplace", "") or ""),
        "order_id": str(parsed.get("order_id", "") or ""),
        "order_time": str(parsed.get("order_time", "") or ""),
        "payment_method": str(parsed.get("payment_method", "") or ""),
        "items": normalized_items,
        "first_image_bytes": first_image_bytes,
    }
