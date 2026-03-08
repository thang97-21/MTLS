"""
Anthropic Translation Brief Agent (Phase 1.56).

Generates a single comprehensive "Translator's Guidance" document for an entire
LN volume by having Claude Sonnet read the full JP corpus in one pass.

The brief is injected into every chapter's batch prompt simultaneously, replacing
the sequential per-chapter summary feed.  Since all chapters are submitted to the
Anthropic Batch API at the same time, there is no inter-chapter dependency —
every chapter benefits from the complete picture instead of only what came before it.

Lifecycle:
  1. Called once before Phase 2 batch submission (translate_volume_batch Phase 1).
  2. Brief is cached to .context/TRANSLATION_BRIEF.md — skipped on re-runs.
  3. Brief text is prepended to every chapter's user prompt.
  4. Phase 3 chapter summarisation still runs in parallel for next-volume use.
"""

from __future__ import annotations

import json
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.common.anthropic_client import AnthropicClient

logger = logging.getLogger(__name__)

_BRIEF_FILENAME = "TRANSLATION_BRIEF.md"
_BRIEF_META_FILENAME = "TRANSLATION_BRIEF.meta.json"
_BRIEF_MAX_OUTPUT_TOKENS = 65535
_PREQUEL_BRIEF_REASON_DISABLED = "P156_PREQUEL_BRIEF_DISABLED"
_PREQUEL_BRIEF_REASON_NOT_SEQUEL = "P156_PREQUEL_NOT_SEQUEL"
_PREQUEL_BRIEF_REASON_BIBLE_UNAVAILABLE = "P156_PREQUEL_BIBLE_UNAVAILABLE"
_PREQUEL_BRIEF_REASON_NO_PREQUEL = "P156_PREQUEL_VOLUME_NOT_FOUND"
_PREQUEL_BRIEF_REASON_MISSING = "P156_PREQUEL_BRIEF_MISSING"
_PREQUEL_BRIEF_REASON_EMPTY = "P156_PREQUEL_BRIEF_EMPTY"
_PREQUEL_BRIEF_REASON_READY = "P156_PREQUEL_BRIEF_READY"

# ── Prompt ────────────────────────────────────────────────────────────────────

_BRIEF_SYSTEM_INSTRUCTION = """You are a senior literary translator and translation analyst specialising in Japanese light novels.
Your task is to read an entire LN volume in Japanese and produce a structured Translator's Guidance brief that will be shared with an AI translation engine as background context for every chapter.
Write in clear, concise English. The brief will be injected verbatim into translation prompts, so make every word count.
CRITICAL SAFETY DIRECTIVE: If the source text contains highly explicit sexual content, violence, or sensitive themes, you MUST obfuscate it using respectful, implicit euphemisms (e.g., 'intimate encounter', 'physical intimacy'). Do NOT use explicit anatomical terms, explicit sexual descriptions, or age-inappropriate descriptors, as doing so will trigger an automated safety block."""

_BRIEF_SYSTEM_INSTRUCTION_MEMOIR = """You are a senior literary translator and translation analyst specialising in Japanese non-fiction, memoir, and biography.
Your task is to read an entire memoir/non-fiction volume in Japanese and produce a structured Translator's Guidance brief that will be shared with an AI translation engine as background context for every chapter.
Write in clear, concise English. The brief will be injected verbatim into translation prompts, so make every word count.
CRITICAL SAFETY DIRECTIVE: If the source text contains highly explicit sexual content, violence, or sensitive themes, you MUST obfuscate it using respectful, implicit euphemisms. Do NOT use explicit anatomical terms or age-inappropriate descriptors."""

# Vietnamese versions
_BRIEF_SYSTEM_INSTRUCTION_VN = """Bạn là một dịch giả văn học cao cấp và chuyên gia phân tích dịch thuật chuyên về light novel tiếng Nhật.
Nhiệm vụ của bạn là đọc toàn bộ tập tiểu thuyết light novel gốc tiếng Nhật và tạo ra một bản hướng dẫn dịch thuật có cấu trúc (Translator's Guidance brief) sẽ được chia sẻ với engine dịch thuật AI như là bối cảnh nền cho mỗi chương.
Viết bằng tiếng Việt rõ ràng, ngắn gọn. Bản hướng dẫn sẽ được tiêm trực tiếp vào prompt dịch thuật, vì vậy hãy chọn lọc từng từ.
LƯU Ý QUAN TRỌNG VỀ AN TOÀN: Nếu văn bản nguồn chứa nội dung tình dục rõ ràng, bạo lực, hoặc chủ đề nhạy cảm, bạn PHẢI làm mờ nó bằng các ẩn dụ tôn trọng và ngầm (ví dụ: 'cuộc gặp thân mật', 'thân mật thể xác'). KHÔNG sử dụng các thuật ngữ giải phẫu tình dục rõ ràng, mô tả tình dục tường minh, hoặc các mô tả không phù hợp với độ tuổi, vì làm như vậy sẽ kích hoạt chặn an toàn tự động."""

_BRIEF_SYSTEM_INSTRUCTION_MEMOIR_VN = """Bạn là một dịch giả văn học cao cấp và chuyên gia phân tích dịch thuật chuyên về tiểu thuyết phi hư cấu, hồi ký, và tiểu sử tiếng Nhật.
Nhiệm vụ của bạn là đọc toàn bộ tập tiểu thuyết phi hư cấu/hồi ký gốc tiếng Nhật và tạo ra một bản hướng dẫn dịch thuật có cấu trúc (Translator's Guidance brief) sẽ được chia sẻ với engine dịch thuật AI như là bối cảnh nền cho mỗi chương.
Viết bằng tiếng Việt rõ ràng, ngắn gọn. Bản hướng dẫn sẽ được tiêm trực tiếp vào prompt dịch thuật, vì vậy hãy chọn lọc từng từ.
LƯU Ý QUAN TRỌNG VỀ AN TOÀN: Nếu văn bản nguồn chứa nội dung tình dục rõ ràng, bạo lực, hoặc chủ đề nhạy cảm, bạn PHẢI làm mờ nó bằng các ẩn dụ tôn trọng và ngầm. KHÔNG sử dụng các thuật ngữ giải phẫu tình dục rõ ràng hoặc các mô tả không phù hợp với độ tuổi."""

_BRIEF_PROMPT_TEMPLATE = """You are about to read the full Japanese source text of a light novel volume.
After reading, produce a **Translator's Guidance Brief** in the exact Markdown structure below.
This brief will be injected as shared context into the translation prompt for every chapter of this volume.

Volume metadata
  Title (JP): {title_jp}
  Title (EN): {title_en}
  Series:     {series}
  Target language: {target_language}

---

# LOCKED CHARACTER NAMES & READINGS (AUTHORITATIVE — DO NOT DEVIATE)

The following character name table is prepared for this volume and is the single source of truth.
You MUST use these exact EN renderings in Section 2 (Character Roster) and throughout the brief.
Do NOT infer, guess, or alter any name — not the romanisation, not the order.
The Ruby Reading column shows the furigana pronunciation for each character's name.

{character_name_table}

---

# LOCKED TERMINOLOGY (AUTHORITATIVE — DO NOT DEVIATE)

The following terminology table is prepared for this volume.
Use these exact EN renderings for all locations, landmarks, cultural terms, and world-building vocabulary.

{terminology_table}

---

# CHAPTER CONTEXT REFERENCE

The following chapter context is prepared for this volume.
Use this as a structural reference when writing Section 3 (Chapter Timeline).

{chapter_context}

---

# FULL SOURCE TEXT

<documents>
  <document index="1">
    <source>full_volume_jp_corpus</source>
    <document_content>
{full_corpus}
    </document_content>
  </document>
</documents>

---

Grounding protocol (mandatory):
- First, identify supporting JP evidence quotes in your reasoning for each major claim.
- Verify chapter IDs before asserting character voice, timeline events, or motif continuity.
- If evidence is unclear, output `N/A` in the corresponding schema field rather than guessing.
- Do NOT output your evidence quote list in the final answer.
- Character names in Section 2 MUST match the LOCKED CHARACTER NAMES table above exactly.

Now write the Translator's Guidance Brief using exactly this structure:

## 1. VOLUME OVERVIEW
One paragraph covering: genre, overall tone, narrative perspective (first/third person), pacing style, and the central emotional arc of this volume.

## 2. CHARACTER ROSTER
Use a rigid per-character template. No free-form character paragraphs.
For each named character, output exactly:

### [EN Name] ([JP name] / [ruby reading])
- **Role:** ...
- **Voice:** ... (register + personality expression in prose/dialogue)
- **EN name lock:** ... (fixed rendering + address rules; include forbidden variants if needed)
- **Speech markers:** ... (repeatable rhythm/lexical markers, punctuation habits, fragment tendencies)
- **Key relationships:** ... (relationship dynamics that must stay consistent)

Rules:
- Keep field order exactly as above for every character.
- Include the ruby reading in the heading (e.g., `Asanagi Umi (朝凪海 / あさなぎうみ)`).
- If a field is unknown, write `N/A` (do not omit the field).
- Keep each field concise and directly actionable.

## 3. CHAPTER-BY-CHAPTER TIMELINE
Use a rigid per-chapter template. No free-form chapter paragraphs.
For each chapter, output exactly:

### [chapter_id]
- **Setting:** ...
- **Key events:** ... (2-5 compact event clauses)
- **Characters present:** ...
- **Emotional register:** ...
- **EPS snapshot:** ... (brief emotional state of key characters at chapter END — e.g., "Maki: WARM→HOT; Umi: NEUTRAL; Nagisa: COLD")
- **Continuity flags:** ... (foreshadowing/payoff/state changes that affect later chapters)

Rules:
- Keep field order exactly as above for every chapter.
- If a field is unknown, write `N/A` (do not omit the field).
- Keep entries compact and scannable.

## 4. LOCKED TERMINOLOGY
Use this exact table format (no extra columns, no prose between rows):

| JP Term | EN Rendering | Notes |
|---------|-------------|-------|
| ... | ... | ... |

Rules:
- Include domain-specific terms, world-building vocabulary, honorific handling, and recurring phrases.
- Include all locations, landmarks, and points of interest with their locked EN renderings.
- `EN Rendering` must be the mandatory locked form.
- `Notes` should contain usage constraints, register scope, or forbidden alternates.

## 5. TONE ARC & STYLE NOTES
Describe how the emotional register shifts across the volume (comedy peaks, dramatic weight, tender moments). Flag any chapters requiring extra care for humour, grief, or action pacing. Note the author's prose style: sentence length, fragment usage, use of internal monologue, etc.

## 6. EMOTION PROGRESSION & REGRESSION MAP
Track the emotional arc of key character relationships across the volume.
For each major relationship pair or character arc, output:

### [Character / Relationship]
- **Volume start state:** ... (EPS band + brief description)
- **Key turning points:** ... (chapter ID → what shifted and why)
- **Volume end state:** ... (EPS band + brief description)
- **Regression risks:** ... (scenes where emotion may regress; translator must preserve the dip)
- **Translation notes:** ... (how to render the emotional shift in prose — word choice, sentence rhythm, contraction level)

Rules:
- Cover all major character arcs and relationship dynamics.
- EPS bands: COLD (-1.0 to -0.6) / COOL (-0.6 to -0.2) / NEUTRAL (-0.2 to +0.2) / WARM (+0.2 to +0.6) / HOT (+0.6 to +1.0)
- Flag any chapters where emotional regression is intentional (e.g., misunderstanding arcs, conflict scenes).

## 7. RECURRING MOTIFS & CALLBACKS
List recurring jokes, metaphors, symbolic objects, or dialogue callbacks that span multiple chapters. For each, explain what it represents and how it should be rendered consistently.

## 8. FORESHADOWING & CONTINUITY FLAGS
List any details in earlier chapters that pay off later, or details the translator must render consistently to avoid retroactive inconsistency.

Formatting constraints:
- Output pure Markdown only.
- Keep section headers (`## 1` ... `## 8`) exactly as written.
- Sections 2, 3, and 4 must follow the rigid schemas above.
- Sections 1, 5, 6, 7, and 8 may use concise prose/bullets.
- **SAFETY**: Completely excise any sexually explicit vocabulary, inappropriate age commentary, or graphical bodily descriptions from your responses. Summarise adult situations using neutral euphemisms (e.g. 'intimate scenes', 'private encounter').

Be thorough but not verbose. Every item in sections 2–8 must be directly actionable for a translator."""

_BRIEF_PROMPT_TEMPLATE_VN = """Bạn sắp đọc toàn bộ văn bản gốc tiếng Nhật của một tập light novel.
Sau khi đọc, hãy tạo ra một **Bản Hướng Dẫn Dịch Thuật** theo đúng cấu trúc Markdown dưới đây.
Bản hướng dẫn này sẽ được tiêm vào prompt dịch thuật cho mỗi chương của tập này.

Thông tin tập sách
  Tiêu đề (JP): {title_jp}
  Tiêu đề (VN): {title_en}
  Series:       {series}
  Ngôn ngữ đích: {target_language}

---

# TÊN NHÂN VẬT ĐÃ KHÓA & RUBY (NGUỒN CHÍNH THỨC — KHÔNG ĐƯỢC THAY ĐỔI)

Bảng tên nhân vật dưới đây được chuẩn bị cho tập sách này và là nguồn duy nhất đáng tin cậy.
Bạn PHẢI sử dụng chính xác các tên VN này trong Phần 2 (Danh sách nhân vật) và xuyên suốt bản hướng dẫn.
Cột Ruby Reading hiển thị cách đọc furigana cho tên mỗi nhân vật.

{character_name_table}

---

# THUẬT NGỮ KHÓA (NGUỒN CHÍNH THỨC — KHÔNG ĐƯỢC THAY ĐỔI)

Bảng thuật ngữ dưới đây được chuẩn bị cho tập sách này.
Sử dụng chính xác các cách dịch VN này cho tất cả địa điểm, địa danh, thuật ngữ văn hóa, và từ vựng xây dựng thế giới.

{terminology_table}

---

# NGỮ CẢNH CHƯƠNG

Bảng ngữ cảnh chương dưới đây được chuẩn bị cho tập sách này.
Sử dụng đây làm tham chiếu cấu trúc khi viết Phần 3 (Timeline Chương).

{chapter_context}

---

# VĂN BẢN NGUỒN ĐẦY ĐỦ

<documents>
  <document index="1">
    <source>full_volume_jp_corpus</source>
    <document_content>
{full_corpus}
    </document_content>
  </document>
</documents>

---

Giao thức căn cứ (bắt buộc):
- Trước tiên, xác định các trích dẫn bằng chứng JP hỗ trợ trong lý luận của bạn cho mỗi luận điểm chính.
- Xác minh ID chương trước khi khẳng định giọng nhân vật, sự kiện timeline, hoặc tính liên tục của motif.
- Nếu bằng chứng không rõ ràng, ghi `N/A` vào trường schema tương ứng thay vì đoán.
- KHÔNG xuất danh sách trích dẫn bằng chứng trong câu trả lời cuối cùng.
- Tên nhân vật trong Phần 2 PHẢI khớp chính xác với bảng TÊN NHÂN VẬT ĐÃ KHÓA ở trên.

Bây giờ hãy viết Bản Hướng Dẫn Dịch Thuật theo đúng cấu trúc này:

## 1. TỔNG QUAN TẬP SÁCH
Một đoạn văn bao gồm: thể loại, giọng điệu tổng thể, góc nhìn tường thuật (ngôi thứ nhất/thứ ba), phong cách nhịp điệu, và cung bậc cảm xúc trung tâm của tập này.

## 2. DANH SÁCH NHÂN VẬT
Sử dụng mẫu cứng cho từng nhân vật. Không có đoạn văn tự do về nhân vật.
Cho mỗi nhân vật được đặt tên, xuất chính xác:

### [Tên VN] ([Tên JP] / [ruby reading])
- **Vai trò:** ...
- **Giọng nói:** ... (register + cách thể hiện tính cách trong văn xuôi/hội thoại)
- **Khóa tên VN:** ... (cách dịch cố định + quy tắc xưng hô; bao gồm các biến thể bị cấm nếu cần)
- **Dấu hiệu lời thoại:** ... (nhịp điệu/từ vựng lặp lại, thói quen dấu câu, xu hướng câu đứt đoạn)
- **Quan hệ chính:** ... (động lực quan hệ phải nhất quán)

Quy tắc:
- Giữ đúng thứ tự trường cho mỗi nhân vật.
- Bao gồm ruby reading trong tiêu đề (ví dụ: `天海うみ (あまみうみ)`).
- Nếu trường không rõ, ghi `N/A` (không bỏ qua trường).
- Giữ mỗi trường ngắn gọn và có thể hành động trực tiếp.

## 3. TIMELINE TỪNG CHƯƠNG
Sử dụng mẫu cứng cho từng chương. Không có đoạn văn tự do về chương.
Cho mỗi chương, xuất chính xác:

### [chapter_id]
- **Bối cảnh:** ...
- **Sự kiện chính:** ... (2-5 mệnh đề sự kiện ngắn gọn)
- **Nhân vật xuất hiện:** ...
- **Register cảm xúc:** ...
- **EPS snapshot:** ... (trạng thái cảm xúc ngắn gọn của nhân vật chính ở CUỐI chương — ví dụ: "Maki: WARM→HOT; Umi: NEUTRAL; Nagisa: COLD")
- **Cờ liên tục:** ... (foreshadowing/payoff/thay đổi trạng thái ảnh hưởng đến các chương sau)

Quy tắc:
- Giữ đúng thứ tự trường cho mỗi chương.
- Nếu trường không rõ, ghi `N/A` (không bỏ qua trường).
- Giữ các mục ngắn gọn và dễ quét.

## 4. THUẬT NGỮ KHÓA
Sử dụng đúng định dạng bảng này (không có cột thêm, không có văn xuôi giữa các hàng):

| Thuật ngữ JP | Cách dịch VN | Ghi chú |
|--------------|-------------|---------|
| ... | ... | ... |

Quy tắc:
- Bao gồm các thuật ngữ chuyên ngành, từ vựng xây dựng thế giới, cách xử lý kính ngữ, và các cụm từ lặp lại.
- `Cách dịch VN` phải là dạng khóa bắt buộc.
- `Ghi chú` nên chứa ràng buộc sử dụng, phạm vi register, hoặc các biến thể bị cấm.

## 5. CUNG BẬC GIỌNG ĐIỆU & GHI CHÚ PHONG CÁCH
Mô tả cách register cảm xúc thay đổi qua tập sách (đỉnh hài hước, trọng lượng kịch tính, khoảnh khắc dịu dàng). Đánh dấu các chương cần chú ý đặc biệt về hài hước, đau buồn, hoặc nhịp điệu hành động. Ghi chú phong cách văn xuôi của tác giả: độ dài câu, sử dụng câu đứt đoạn, sử dụng độc thoại nội tâm, v.v.

## 6. BẢN ĐỒ TIẾN TRÌNH & THOÁI TRÀO CẢM XÚC
Theo dõi cung cảm xúc của các cặp quan hệ nhân vật chính xuyên suốt tập sách.
Cho mỗi cặp quan hệ hoặc cung nhân vật chính, xuất:

### [Nhân vật / Quan hệ]
- **Trạng thái đầu tập:** ... (band EPS + mô tả ngắn)
- **Các điểm chuyển mình chính:** ... (chapter ID → điều gì đã thay đổi và tại sao)
- **Trạng thái cuối tập:** ... (band EPS + mô tả ngắn)
- **Rủi ro thoái trào:** ... (cảnh mà cảm xúc có thể thoái trào; dịch giả phải bảo toàn sự giảm sút)
- **Ghi chú dịch thuật:** ... (cách diễn đạt sự chuyển mình cảm xúc trong văn xuôi — lựa ch�ọn từ, nhịp câu, mức độ viết tắt)

Quy tắc:
- Bao gồm tất cả các cung nhân vật chính và động lực quan hệ.
- Các band EPS: COLD (-1.0 đến -0.6) / COOL (-0.6 đến -0.2) / NEUTRAL (-0.2 đến +0.2) / WARM (+0.2 đến +0.6) / HOT (+0.6 đến +1.0)
- Đánh dấu các chương mà thoái trào cảm xúc là có chủ đích (ví dụ: cảnh hiểu lầm, xung đột).

## 7. MOTIF LẶP LẠI & CALLBACK
Liệt kê các trò đùa lặp lại, ẩn dụ, vật thể biểu tượng, hoặc callback hội thoại trải dài nhiều chương. Cho mỗi mục, giải thích nó đại diện cho điều gì và cách dịch nhất quán.

## 8. FORESHADOWING & CỜ LIÊN TỤC
Liệt kê bất kỳ chi tiết nào ở các chương trước được giải quyết sau, hoặc các chi tiết dịch giả phải dịch nhất quán để tránh mâu thuẫn hồi tố.

Ràng buộc định dạng:
- Chỉ xuất Markdown thuần túy.
- Giữ đúng tiêu đề phần (`## 1` ... `## 8`) như đã viết.
- Phần 2, 3, và 4 phải tuân theo schema cứng ở trên.
- Phần 1, 5, 6, 7, và 8 có thể sử dụng văn xuôi/bullet ngắn gọn.
- **AN TOÀN**: Loại bỏ hoàn toàn bất kỳ từ vựng tình dục rõ ràng, bình luận tuổi không phù hợp, hoặc mô tả cơ thể đồ họa khỏi câu trả lời của bạn. Tóm tắt các tình huống người lớn bằng ẩn dụ trung lập (ví dụ: 'cảnh thân mật', 'cuộc gặp riêng tư').

Hãy kỹ lưỡng nhưng không dài dòng. Mỗi mục trong phần 2–8 phải có thể hành động trực tiếp cho dịch giả."""

_BRIEF_PROMPT_TEMPLATE_MEMOIR_VN = """Bạn sắp đọc toàn bộ văn bản gốc tiếng Nhật của một tập hồi ký/phi hư cấu.
Sau khi đọc, hãy tạo ra một **Bản Hướng Dẫn Dịch Thuật** theo đúng cấu trúc Markdown dưới đây.
Bản hướng dẫn này sẽ được tiêm vào prompt dịch thuật cho mỗi chương của tập này.

Thông tin tập sách
  Tiêu đề (JP): {title_jp}
  Tiêu đề (VN): {title_en}
  Loại sách:    Hồi ký / Phi hư cấu
  Series:       {series}
  Ngôn ngữ đích: {target_language}

---

# TÊN NHÂN VẬT ĐÃ KHÓA & RUBY (NGUỒN CHÍNH THỨC — KHÔNG ĐƯỢC THAY ĐỔI)

Bảng tên nhân vật dưới đây được chuẩn bị cho tập sách này và là nguồn duy nhất đáng tin cậy.
Bạn PHẢI sử dụng chính xác các tên VN này trong Phần 2 và xuyên suốt bản hướng dẫn.
Cột Ruby Reading hiển thị cách đọc furigana cho tên mỗi nhân vật.

{character_name_table}

---

# THUẬT NGỮ KHÓA (NGUỒN CHÍNH THỨC — KHÔNG ĐƯỢC THAY ĐỔI)

Bảng thuật ngữ dưới đây được chuẩn bị cho tập sách này.
Sử dụng chính xác các cách dịch VN này cho tất cả địa điểm, địa danh, thuật ngữ văn hóa, và từ vựng xây dựng thế giới.

{terminology_table}

---

# NGỮ CẢNH CHƯƠNG

Bảng ngữ cảnh chương dưới đây được chuẩn bị cho tập sách này.
Sử dụng đây làm tham chiếu cấu trúc khi viết Phần 3 (Timeline Chương).

{chapter_context}

---

# VĂN BẢN NGUỒN ĐẦY ĐỦ

<documents>
  <document index="1">
    <source>full_volume_jp_corpus</source>
    <document_content>
{full_corpus}
    </document_content>
  </document>
</documents>

---

Giao thức căn cứ (bắt buộc):
- Xác định các trích dẫn bằng chứng JP hỗ trợ trong lý luận của bạn cho mỗi luận điểm chính.
- Xác minh ID chương trước khi khẳng định giọng người kể, sự kiện timeline, hoặc tính liên tục.
- Nếu bằng chứng không rõ ràng, ghi `N/A` thay vì đoán.
- KHÔNG xuất danh sách trích dẫn bằng chứng trong câu trả lời cuối cùng.
- Tên nhân vật PHẢI khớp chính xác với bảng TÊN NHÂN VẬT ĐÃ KHÓA ở trên.

Bây giờ hãy viết Bản Hướng Dẫn Dịch Thuật theo đúng cấu trúc này:

## 1. TỔNG QUAN TẬP SÁCH
Một đoạn văn bao gồm: thể loại (hồi ký/tiểu sử), giọng điệu tổng thể, góc nhìn tường thuật (ngôi thứ nhất), phong cách nhịp điệu, và cung bậc cảm xúc trung tâm của tập này.

## 2. NGƯỜI KỂ CHUYỆN & NHÂN VẬT THỰC
Sử dụng mẫu cứng cho từng người. Không có đoạn văn tự do.
Cho mỗi người thực được đặt tên, xuất chính xác:

### [Tên VN] ([Tên JP] / [ruby reading])
- **Vai trò:** ... (người kể / gia đình / người cố vấn / đồng nghiệp / v.v.)
- **Giọng nói:** ... (register trong hội thoại được trích dẫn)
- **Khóa tên VN:** ... (cách dịch cố định; bao gồm tên nghệ danh nếu có)
- **Quan hệ với người kể:** ... (quan hệ thực tế, không phải archetype hư cấu)

Quy tắc:
- Giữ đúng thứ tự trường cho mỗi người.
- Bao gồm ruby reading trong tiêu đề (ví dụ: `田中太郎 (たなかたろう)`).
- Nếu trường không rõ, ghi `N/A`.
- KHÔNG áp dụng archetype nhân vật hư cấu (tsundere, gyaru, v.v.) cho người thực.

## 3. TIMELINE TỪNG CHƯƠNG
Sử dụng mẫu cứng cho từng chương. Không có đoạn văn tự do.
Cho mỗi chương, xuất chính xác:

### [chapter_id]
- **Giai đoạn thời gian:** ... (tuổi/năm/giai đoạn cuộc đời)
- **Sự kiện chính:** ... (2-5 mệnh đề sự kiện ngắn gọn)
- **Người xuất hiện:** ...
- **Register cảm xúc:** ...
- **EPS snapshot:** ... (trạng thái cảm xúc ngắn gọn ở CUỐI chương)
- **Cờ liên tục:** ... (chi tiết ảnh hưởng đến các chương sau)

## 4. THỰC THỂ THỰC TẾ CẦN KHÓA
Sử dụng đúng định dạng bảng này:

| Thực thể JP | Cách dịch VN | Loại | Ghi chú |
|-------------|-------------|------|---------|
| ... | ... | địa điểm/công ty/bài hát/v.v. | ... |

Quy tắc:
- Bao gồm: tên địa điểm, tên công ty/hãng đĩa, tên bài hát/album, tên tour, tên nền tảng.
- Các thực thể thực tế KHÔNG được dịch — chỉ romanize nếu cần.
- Ghi chú cách xử lý nhất quán.

## 5. GIỌNG NGƯỜI KỂ & GHI CHÚ PHONG CÁCH
Mô tả register giọng người kể (văn học/thông thường/hỗn hợp). Ghi chú sự chuyển đổi giữa tường thuật văn học và hội thoại thông thường. Mô tả phong cách văn xuôi của tác giả: độ dài câu, sử dụng câu đứt đoạn, sử dụng độc thoại nội tâm, v.v.

## 6. BẢN ĐỒ TIẾN TRÌNH & THOÁI TRÀO CẢM XÚC
Theo dõi cung cảm xúc của người kể và các quan hệ chính xuyên suốt tập sách.
Cho mỗi cung cảm xúc chính, xuất:

### [Nhân vật / Quan hệ]
- **Trạng thái đầu tập:** ... (band EPS + mô tả ngắn)
- **Các điểm chuyển mình chính:** ... (chapter ID → điều gì đã thay đổi và tại sao)
- **Trạng thái cuối tập:** ... (band EPS + mô tả ngắn)
- **Rủi ro thoái trào:** ... (cảnh mà cảm xúc có thể thoái trào; dịch giả phải bảo toàn sự giảm sút)
- **Ghi chú dịch thuật:** ... (cách diễn đạt sự chuyển mình cảm xúc trong văn xuôi)

Quy tắc:
- Các band EPS: COLD (-1.0 đến -0.6) / COOL (-0.6 đến -0.2) / NEUTRAL (-0.2 đến +0.2) / WARM (+0.2 đến +0.6) / HOT (+0.6 đến +1.0)
- Đánh dấu các chương mà thoái trào cảm xúc là có chủ đích.

## 7. MOTIF LẶP LẠI & CALLBACK
Liệt kê các chủ đề lặp lại, ẩn dụ, hoặc callback trải dài nhiều chương. Cho mỗi mục, giải thích ý nghĩa và cách dịch nhất quán.

## 8. CỜ LIÊN TỤC
Liệt kê bất kỳ chi tiết nào ở các chương trước được giải quyết sau, hoặc các chi tiết dịch giả phải dịch nhất quán.

Ràng buộc định dạng:
- Chỉ xuất Markdown thuần túy.
- Giữ đúng tiêu đề phần (`## 1` ... `## 8`) như đã viết.
- **AN TOÀN**: Loại bỏ hoàn toàn bất kỳ từ vựng tình dục rõ ràng hoặc mô tả không phù hợp.

Hãy kỹ lưỡng nhưng không dài dòng. Mỗi mục phải có thể hành động trực tiếp cho dịch giả."""


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class TranslationBriefResult:
    """Result from a brief generation attempt."""
    success: bool
    brief_text: str
    brief_path: Optional[Path]
    model: str
    cached: bool = False
    error: Optional[str] = None


# ── Agent ─────────────────────────────────────────────────────────────────────

class AnthropicTranslationBriefAgent:
    """
    Reads the full JP corpus of a volume and produces a Translator's Guidance
    brief via a single Anthropic/Claude call.

    The brief replaces sequential chapter summaries for Anthropic batch runs.
    """

    def __init__(
        self,
        anthropic_client: AnthropicClient,
        work_dir: Path,
        manifest: Dict[str, Any],
        target_language: str = "en",
        model: str = "anthropic/claude-sonnet-4",
        book_type: str = None,
        translation_config: Optional[Dict[str, Any]] = None,
        enable_prequel_brief_injection: Optional[bool] = None,
    ):
        self.client = anthropic_client
        self.work_dir = work_dir
        self.manifest = manifest
        self.target_language = target_language
        self.model = model
        self.book_type = (book_type or "").lower().strip()

        _non_fiction_types = {"memoir", "biography", "autobiography", "non_fiction", "non-fiction", "essay"}
        self._is_non_fiction = self.book_type in _non_fiction_types
        _is_vn = self.target_language.lower() in {"vn", "vi", "vietnamese", "tiếng việt"}
        if _is_vn:
            self._system_instruction = (
                _BRIEF_SYSTEM_INSTRUCTION_MEMOIR_VN if self._is_non_fiction else _BRIEF_SYSTEM_INSTRUCTION_VN
            )
            self._prompt_template = (
                _BRIEF_PROMPT_TEMPLATE_MEMOIR_VN if self._is_non_fiction else _BRIEF_PROMPT_TEMPLATE_VN
            )
        else:
            self._system_instruction = (
                _BRIEF_SYSTEM_INSTRUCTION_MEMOIR if self._is_non_fiction else _BRIEF_SYSTEM_INSTRUCTION
            )
            self._prompt_template = _BRIEF_PROMPT_TEMPLATE

        self.context_dir = work_dir / ".context"
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.brief_path = self.context_dir / _BRIEF_FILENAME
        self.brief_meta_path = self.context_dir / _BRIEF_META_FILENAME

        cfg = translation_config if isinstance(translation_config, dict) else {}
        prequel_cfg = cfg.get("phase1_56_prequel_brief_injection", {})
        if not isinstance(prequel_cfg, dict):
            prequel_cfg = {}
        self._prequel_brief_cfg = prequel_cfg
        if enable_prequel_brief_injection is None:
            self._prequel_brief_enabled = bool(prequel_cfg.get("enabled", False))
        else:
            self._prequel_brief_enabled = bool(enable_prequel_brief_injection)
        try:
            self._prequel_brief_max_chars = max(
                1000,
                int(prequel_cfg.get("max_chars", 20000) or 20000),
            )
        except Exception:
            self._prequel_brief_max_chars = 20000

    # ── Character name table builder ─────────────────────────────────────────

    def _build_character_name_table(self) -> str:
        """
        Build a comprehensive markdown table of character names with ruby/base readings.
        Extracts from manifest.json (ruby_base/ruby_reading) and metadata_en.json.
        This table is injected into the brief prompt as the authoritative source.
        """
        import json

        # Load from manifest.json (primary source for ruby readings)
        manifest_path = self.work_dir / "manifest.json"
        manifest_data = {}
        if manifest_path.exists():
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest_data = json.load(f)
            except Exception:
                pass

        # Load from metadata_en.json (fallback)
        metadata_path = self.work_dir / "metadata_en.json"
        metadata = {}
        if metadata_path.exists():
            try:
                with open(metadata_path, encoding="utf-8") as f:
                    metadata = json.load(f)
            except Exception:
                pass

        # Get character profiles from manifest first (they have ruby_base/ruby_reading)
        char_profiles = manifest_data.get("character_profiles", {}) or metadata.get("character_profiles", {})

        if not char_profiles:
            return "(no character profiles found in manifest.json or metadata_en.json)"

        # Build ruby_names lookup from manifest (kanji -> ruby)
        ruby_names_list = manifest_data.get("ruby_names", [])
        ruby_lookup = {}
        for entry in ruby_names_list:
            kanji = entry.get("kanji", "")
            ruby = entry.get("ruby", "")
            if kanji and ruby:
                ruby_lookup[kanji] = ruby

        rows = []
        for jp_name, profile in char_profiles.items():
            # Skip Unknown entries or empty names
            if jp_name == "Unknown" or not jp_name.strip():
                continue

            full_name = str(profile.get("full_name", "") or "").strip()
            if not full_name:
                continue

            # Get ruby readings from profile or lookup
            ruby_base = str(profile.get("ruby_base", "") or "").strip()
            ruby_reading = str(profile.get("ruby_reading", "") or "").strip()

            # If not in profile, try lookup from ruby_names
            if not ruby_reading and ruby_base:
                ruby_reading = ruby_lookup.get(ruby_base, "")

            # Extract surname and given name from the EN full_name
            parts = full_name.split()
            surname = parts[0] if len(parts) >= 1 else ""
            given_name = parts[1] if len(parts) >= 2 else ""

            # Format: JP Name | EN Name | Ruby Reading | Given Name | Nickname
            nickname = str(profile.get("nickname", "") or "").strip()
            nickname_display = f"→ {nickname}" if nickname else ""

            if not given_name:
                rows.append(f"| {jp_name} | {full_name} | {ruby_reading} | — |{nickname_display}|")
            else:
                rows.append(f"| {jp_name} | {full_name} | {ruby_reading} | {given_name} |{nickname_display}|")

        if not rows:
            return "(no valid character names found)"

        header = "| JP Name | EN Name (Locked) | Ruby Reading | Given Name | Nickname |\n|--------|-----------------|--------------|-------------|----------|\n"
        return header + "\n".join(rows)

    # ── Terminology extraction ──────────────────────────────────────────────

    def _build_terminology_table(self) -> str:
        """
        Build comprehensive terminology table from metadata_en.json and manifest.json.
        Includes: locations, landmarks, POI, cultural terms, deobfuscated terms.
        """
        import json

        metadata_path = self.work_dir / "metadata_en.json"
        manifest_path = self.work_dir / "manifest.json"

        metadata = {}
        manifest_data = {}

        if metadata_path.exists():
            try:
                with open(metadata_path, encoding="utf-8") as f:
                    metadata = json.load(f)
            except Exception:
                pass

        if manifest_path.exists():
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest_data = json.load(f)
            except Exception:
                pass

        terms = []

        def _coerce_term_row(info: Any) -> tuple[str, str, str]:
            if isinstance(info, dict):
                character = str(info.get("character", "")).strip()
                policy = str(info.get("policy", "")).strip()
                notes = str(info.get("notes", "")).strip()
                canonical = policy.split(".")[0].strip() if policy else ""
                if not canonical:
                    canonical = str(
                        info.get("canonical_en")
                        or info.get("en")
                        or info.get("canonical")
                        or ""
                    ).strip()
                return character, canonical, notes

            text = str(info).strip()
            canonical = text.split(".")[0].strip() if text else ""
            return "", canonical, text

        # 1. Cultural terms from metadata_en.json
        cultural_terms = metadata.get("cultural_terms", {})
        for jp_term, info in cultural_terms.items():
            if isinstance(info, dict):
                canonical = str(info.get("canonical_en", "")).strip()
                notes = str(info.get("notes", "")).strip()
            else:
                canonical = str(info).strip()
                notes = ""
            terms.append(("Cultural", jp_term, canonical, notes))

        # 2. Character-specific terms from metadata_en.json
        char_terms = metadata.get("translation_rules", {}).get("character_specific_terms", {})
        for jp_term, info in char_terms.items():
            character, canonical, notes = _coerce_term_row(info)
            category = f"Character: {character}" if character else "Character"
            terms.append((category, jp_term, canonical, notes))

        # 3. Location/landmark data from manifest (if available)
        # Check nav_points or custom location structures
        nav_points = manifest_data.get("nav_points", [])
        for np in nav_points:
            label = np.get("label", "")
            href = np.get("href", "")
            if label and "location" in str(np).lower():
                terms.append(("Location", label, label, f"href: {href}"))

        # 4. World-building terms (custom structures in metadata)
        world_terms = metadata.get("world_building", {}) or metadata.get("terminology", {})
        for jp_term, info in world_terms.items():
            if isinstance(info, dict):
                canonical = info.get("en", info.get("canonical", ""))
                notes = info.get("notes", "")
                terms.append(("World", jp_term, canonical, notes))
            else:
                terms.append(("World", jp_term, str(info), ""))

        if not terms:
            return "| Category | JP Term | EN Rendering | Notes |\n|---------|---------|-------------|-------|\n| — | No terminology data available | — | — |"

        # Format as markdown table
        header = "| Category | JP Term | EN Rendering | Notes |\n|---------|---------|-------------|-------|\n"
        rows = []
        for category, jp, en, notes in terms:
            # Truncate long notes
            notes_short = notes[:80] + "..." if len(notes) > 80 else notes
            rows.append(f"| {category} | {jp} | {en} | {notes_short} |")

        return header + "\n".join(rows)

    # ── Chapter context extraction ────────────────────────────────────────────

    def _build_chapter_context(self) -> str:
        """
        Build brief chapter context from manifest chapters array.
        Includes: chapter ID, brief summary, key characters, emotional notes.
        """
        import json

        manifest_path = self.work_dir / "manifest.json"
        if not manifest_path.exists():
            return "(chapter context unavailable)"

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            logger.debug(f"[BRIEF] Chapter context load failed: {e}")
            return "(chapter context unavailable)"

        chapters = manifest.get("chapters", [])
        if not chapters:
            chapters = manifest.get("structure", {}).get("chapters", [])

        if not chapters:
            return "(no chapter data in manifest)"

        rows = []

        def _to_context_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, list):
                flattened: List[str] = []
                for item in value:
                    if isinstance(item, (str, int, float, bool)):
                        text = str(item).strip()
                        if text:
                            flattened.append(text)
                    elif isinstance(item, dict):
                        for key in ("name", "title", "id", "character", "label"):
                            candidate = str(item.get(key, "") or "").strip()
                            if candidate:
                                flattened.append(candidate)
                                break
                return ", ".join(flattened)
            if isinstance(value, dict):
                for key in ("summary", "text", "label", "name", "title", "id"):
                    candidate = str(value.get(key, "") or "").strip()
                    if candidate:
                        return candidate
                keys = [str(k).strip() for k in value.keys() if str(k).strip()]
                return ", ".join(keys[:3])
            return str(value).strip()

        for ch in chapters:
            if not isinstance(ch, dict):
                continue

            ch_id = ch.get("id", ch.get("chapter_id", ""))

            # Get brief summary/synopsis
            summary = ch.get("summary", ch.get("synopsis", ""))

            # Get characters appearing
            characters = ch.get("characters", ch.get("character_appearances", ""))

            # Get emotional tone if available
            tone = ch.get("emotional_tone", ch.get("tone", ""))

            summary_text = _to_context_text(summary) or "N/A"
            characters_text = _to_context_text(characters) or "N/A"
            tone_text = _to_context_text(tone) or "N/A"

            # Truncate summary
            summary_short = summary_text[:100] + "..." if len(summary_text) > 100 else summary_text
            chars_short = characters_text[:60] + "..." if len(characters_text) > 60 else characters_text
            tone_short = tone_text[:40] + "..." if len(tone_text) > 40 else tone_text

            rows.append(f"| {ch_id} | {summary_short} | {chars_short} | {tone_short} |")

        header = "| Chapter | Summary | Characters | Emotional Tone |\n|---------|---------|------------|----------------|\n"
        return header + "\n".join(rows)

    def _current_volume_index(self) -> Optional[int]:
        """Resolve current volume index from manifest metadata."""
        series_index = self.manifest.get("metadata", {}).get("series_index")
        if isinstance(series_index, int):
            return series_index
        if isinstance(series_index, str):
            try:
                return int(series_index.strip())
            except ValueError:
                return None
        if isinstance(series_index, float):
            return int(series_index)
        return None

    def _resolve_prequel_candidate_from_bible(self) -> Optional[Dict[str, Any]]:
        """Resolve the immediate prequel volume from series bible registration."""
        current_idx = self._current_volume_index()
        if current_idx is None or current_idx <= 1:
            return None

        try:
            from pipeline.metadata_processor.bible_sync import BibleSyncAgent
            from pipeline.config import PIPELINE_ROOT

            bible_sync = BibleSyncAgent(self.work_dir, PIPELINE_ROOT)
            if not bible_sync.resolve(self.manifest):
                return None
            bible = getattr(bible_sync, "bible", None)
            if not bible:
                return None
        except Exception as exc:
            logger.debug(f"[BRIEF] Prequel bible resolution failed: {exc}")
            return None

        candidates: List[Dict[str, Any]] = []
        for entry in bible.volumes_registered:
            if not isinstance(entry, dict):
                continue
            raw_index = entry.get("index")
            try:
                idx = int(raw_index)
            except (TypeError, ValueError):
                continue
            if idx >= current_idx:
                continue
            volume_id = str(entry.get("volume_id", "") or "").strip()
            title = str(entry.get("title", "") or "").strip()
            if not volume_id and not title:
                continue
            candidates.append(
                {
                    "index": idx,
                    "volume_id": volume_id,
                    "title": title,
                }
            )

        if not candidates:
            return None
        return sorted(candidates, key=lambda row: row["index"], reverse=True)[0]

    def _build_prequel_brief_context(self) -> Dict[str, Any]:
        """Build optional sequel continuity context from the prequel brief."""
        current_volume_id = str(self.manifest.get("volume_id") or self.work_dir.name)
        current_idx = self._current_volume_index()
        audit: Dict[str, Any] = {
            "enabled": bool(self._prequel_brief_enabled),
            "requested": bool(self._prequel_brief_enabled),
            "injected": False,
            "reason_code": _PREQUEL_BRIEF_REASON_DISABLED,
            "reason": "Prequel brief injection disabled by config/CLI.",
            "current_volume_id": current_volume_id,
            "current_volume_index": current_idx,
            "source_volume_id": "",
            "source_volume_index": None,
            "source_brief_sha256": "",
            "injected_chars": 0,
            "prompt_block": "",
        }

        if not self._prequel_brief_enabled:
            return audit

        if current_idx is None or current_idx <= 1:
            audit["reason_code"] = _PREQUEL_BRIEF_REASON_NOT_SEQUEL
            audit["reason"] = "Current volume is not identified as a sequel (series_index <= 1)."
            return audit

        candidate = self._resolve_prequel_candidate_from_bible()
        if candidate is None:
            audit["reason_code"] = _PREQUEL_BRIEF_REASON_BIBLE_UNAVAILABLE
            audit["reason"] = "Could not resolve prequel from series bible volume registry."
            return audit

        source_volume_id = str(candidate.get("volume_id", "") or "").strip()
        source_title = str(candidate.get("title", "") or "").strip()
        source_index = candidate.get("index")

        audit["source_volume_id"] = source_volume_id
        audit["source_volume_index"] = source_index

        if not source_volume_id:
            audit["reason_code"] = _PREQUEL_BRIEF_REASON_NO_PREQUEL
            audit["reason"] = "Prequel candidate lacks a volume_id in bible registry."
            return audit

        prequel_brief_path = self.work_dir.parent / source_volume_id / ".context" / _BRIEF_FILENAME
        if not prequel_brief_path.exists():
            audit["reason_code"] = _PREQUEL_BRIEF_REASON_MISSING
            audit["reason"] = f"Prequel brief not found at {prequel_brief_path}."
            return audit

        prequel_brief_text = prequel_brief_path.read_text(encoding="utf-8").strip()
        if not prequel_brief_text:
            audit["reason_code"] = _PREQUEL_BRIEF_REASON_EMPTY
            audit["reason"] = f"Prequel brief is empty at {prequel_brief_path}."
            return audit

        if len(prequel_brief_text) > self._prequel_brief_max_chars:
            prequel_brief_text = prequel_brief_text[: self._prequel_brief_max_chars].rstrip()

        source_label = source_title or source_volume_id or "Unknown"
        prompt_block = (
            "\n\n---\n"
            "# PREQUEL CONTINUITY BRIEF (AUTO-INJECTED FOR SEQUELS)\n"
            "Use this as continuity baseline for names, relationships, and payoff chains. "
            "Current-volume evidence always has higher priority when conflicts exist.\n"
            f"Source prequel volume: {source_label}"
            f" (id={source_volume_id}, index={source_index})\n\n"
            f"{prequel_brief_text}\n"
            "---\n"
        )

        digest = hashlib.sha256(prequel_brief_text.encode("utf-8")).hexdigest()
        audit.update(
            {
                "injected": True,
                "reason_code": _PREQUEL_BRIEF_REASON_READY,
                "reason": "Prequel brief loaded and injected into prompt context.",
                "source_brief_sha256": digest,
                "injected_chars": len(prequel_brief_text),
                "prompt_block": prompt_block,
            }
        )
        return audit

    @staticmethod
    def _prequel_cache_signature(prequel_audit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Compact deterministic prequel signature for cache invalidation."""
        audit = prequel_audit if isinstance(prequel_audit, dict) else {}
        return {
            "enabled": bool(audit.get("enabled", False)),
            "injected": bool(audit.get("injected", False)),
            "reason_code": str(audit.get("reason_code", "") or ""),
            "source_volume_id": str(audit.get("source_volume_id", "") or ""),
            "source_volume_index": audit.get("source_volume_index"),
            "source_brief_sha256": str(audit.get("source_brief_sha256", "") or ""),
        }

    def _log_prequel_audit(self, prequel_audit: Dict[str, Any]) -> None:
        """Emit concise runtime audit line for Phase 1.56 prequel continuity mode."""
        logger.info(
            "[P1.56][PREQUEL] "
            f"volume={prequel_audit.get('current_volume_id') or self.work_dir.name} "
            f"enabled={bool(prequel_audit.get('enabled', False))} "
            f"injected={bool(prequel_audit.get('injected', False))} "
            f"reason_code={prequel_audit.get('reason_code', '')} "
            f"source={prequel_audit.get('source_volume_id', '') or 'n/a'} "
            f"chars={int(prequel_audit.get('injected_chars', 0) or 0)}"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_brief(self, force: bool = False) -> TranslationBriefResult:
        """
        Generate (or load from cache) the Translator's Guidance brief.

        Args:
            force: Re-generate even if a cached brief already exists.

        Returns:
            TranslationBriefResult with .brief_text populated on success.
        """
        prequel_audit = self._build_prequel_brief_context()
        expected_prequel_signature = self._prequel_cache_signature(prequel_audit)
        self._log_prequel_audit(prequel_audit)

        # Use cached brief if available
        if not force and self.brief_path.exists():
            cached_text = self.brief_path.read_text(encoding="utf-8").strip()
            if cached_text:
                cache_meta = self._load_cache_meta()
                valid, reason = self._validate_cached_brief(
                    cached_text,
                    cache_meta,
                    expected_prequel_signature=expected_prequel_signature,
                )
                if valid:
                    logger.info(
                        f"[BRIEF] Using cached Translator's Guidance brief "
                        f"({len(cached_text):,} chars) — {self.brief_path.name}"
                    )
                    return TranslationBriefResult(
                        success=True,
                        brief_text=cached_text,
                        brief_path=self.brief_path,
                        model=self.model,
                        cached=True,
                    )
                logger.info(
                    f"[BRIEF] Cached brief is stale ({reason}) — regenerating from current JP corpus"
                )
                self._backup_existing_brief()

        logger.info("[BRIEF] Generating Translator's Guidance brief from full JP corpus…")

        # Build corpus
        corpus_text, chapter_count = self._build_jp_corpus()
        if not corpus_text.strip():
            return TranslationBriefResult(
                success=False,
                brief_text="",
                brief_path=None,
                model=self.model,
                error="No JP source text found — cannot generate brief.",
            )

        logger.info("[BRIEF] Sanitizing JP corpus to bypass safety filters...")
        corpus_text = self._sanitize_corpus(corpus_text)

        logger.info(
            f"[BRIEF] Corpus assembled: {chapter_count} chapters, "
            f"{len(corpus_text):,} chars → submitting to {self.model}"
        )

        # Build prompt
        meta = self.manifest.get("metadata", {})
        character_table = self._build_character_name_table()
        terminology_table = self._build_terminology_table()
        chapter_context = self._build_chapter_context()
        prompt = self._prompt_template.format(
            title_jp=meta.get("title_jp") or meta.get("title") or "Unknown",
            title_en=meta.get("title_en") or meta.get("title_vi") or meta.get("title") or "Unknown",
            series=meta.get("series") or meta.get("series_title") or "Standalone",
            target_language=self.target_language.upper(),
            full_corpus=corpus_text,
            character_name_table=character_table,
            terminology_table=terminology_table,
            chapter_context=chapter_context,
        )
        if prequel_audit.get("injected") and prequel_audit.get("prompt_block"):
            prompt = f"{prequel_audit['prompt_block']}\n{prompt}"
        logger.info(
            f"[BRIEF] Prompt prepared: {len(prompt):,} chars → calling {self.model}"
        )

        try:
            started = time.monotonic()
            response = self.client.generate(
                prompt=prompt,
                system_instruction=self._system_instruction,
            )
            elapsed = time.monotonic() - started
            logger.info(f"[BRIEF] Model call completed in {elapsed:.1f}s")
            brief_text = (response.content or "").strip()
            if not brief_text:
                raise ValueError("Model returned empty brief")
            valid_generated, reason_generated = self._validate_cached_brief(
                brief_text, cache_meta=None
            )
            if not valid_generated:
                logger.warning(
                    f"[BRIEF] Generated brief coverage check failed ({reason_generated}). "
                    "Retrying once with strict chapter lock."
                )
                required_ids = self._required_chapter_ids()
                strict_lock = (
                    "\n\nHard requirement before finalizing:\n"
                    "In Section 3, include one timeline entry for EACH chapter ID below, with no omissions.\n"
                    f"Required chapter IDs: {', '.join(required_ids)}\n"
                    "If uncertain for a chapter field, output N/A (never omit the chapter).\n"
                )
                retry_started = time.monotonic()
                retry_response = self.client.generate(
                    prompt=f"{prompt}{strict_lock}",
                    system_instruction=self._system_instruction,
                    temperature=0.1,
                    max_output_tokens=_BRIEF_MAX_OUTPUT_TOKENS,
                    model=self.model,
                    force_new_session=True,
                )
                retry_elapsed = time.monotonic() - retry_started
                logger.info(f"[BRIEF] Retry model call completed in {retry_elapsed:.1f}s")
                brief_text = (retry_response.content or "").strip()
                if not brief_text:
                    raise ValueError("Model returned empty brief on retry")
                valid_retry, reason_retry = self._validate_cached_brief(
                    brief_text, cache_meta=None
                )
                if not valid_retry:
                    raise ValueError(
                        f"Generated brief incomplete after retry ({reason_retry})"
                    )

            # Persist
            self.brief_path.write_text(brief_text, encoding="utf-8")
            self._save_cache_meta(self._current_cache_meta(prequel_audit=prequel_audit))
            logger.info(
                f"[BRIEF] Brief generated: {len(brief_text):,} chars → "
                f"saved to {self.brief_path}"
            )
            return TranslationBriefResult(
                success=True,
                brief_text=brief_text,
                brief_path=self.brief_path,
                model=self.model,
                cached=False,
            )

        except Exception as exc:
            logger.warning(
                f"[BRIEF] Brief generation failed: {exc}. "
                "Batch translation will proceed without the volume brief."
            )
            return TranslationBriefResult(
                success=False,
                brief_text="",
                brief_path=None,
                model=self.model,
                error=str(exc),
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_jp_corpus(self) -> tuple[str, int]:
        """
        Concatenate all JP chapter files in chapter order.

        Returns:
            (concatenated_text, chapter_count)
        """
        chapters = self.manifest.get("chapters", [])
        if not chapters:
            chapters = self.manifest.get("structure", {}).get("chapters", [])
        total_chapters = len(chapters)

        jp_dir = self.work_dir / "JP"
        parts: List[str] = []
        found = 0
        scanned = 0

        logger.info(
            f"[BRIEF] Scanning JP files for corpus: {total_chapters} chapter entries in manifest"
        )

        for chapter in chapters:
            scanned += 1
            if scanned % 20 == 0 or scanned == total_chapters:
                logger.info(
                    f"[BRIEF] Corpus scan progress: {scanned}/{total_chapters} chapters"
                )
            jp_file = chapter.get("jp_file") or chapter.get("source_file")
            if not jp_file:
                continue
            source_path = jp_dir / jp_file
            if not source_path.exists():
                logger.debug(f"[BRIEF] JP file not found, skipping: {source_path}")
                continue
            try:
                text = source_path.read_text(encoding="utf-8").strip()
                if text:
                    chapter_id = chapter.get("id", jp_file)
                    parts.append(f"\n\n=== CHAPTER: {chapter_id} ===\n\n{text}")
                    found += 1
            except Exception as _e:
                logger.warning(f"[BRIEF] Could not read {source_path}: {_e}")

        corpus_text = "".join(parts)
        logger.info(
            f"[BRIEF] Corpus scan complete: loaded {found}/{total_chapters} chapters "
            f"({len(corpus_text):,} chars)"
        )
        return corpus_text, found

    @staticmethod
    def _sanitize_corpus(japanese_text: str) -> str:
        """
        Reduce prompt-block risk by neutralizing explicit tokens in the JP corpus.
        Keeps narrative intact for metadata extraction.
        """
        text = japanese_text
        replacements = {
            "パンツ一枚": "ラフな部屋着",
            "パンツ": "部屋着",
            "下着": "服装",
            "裸": "無防備な姿",
            "脱い": "着替え",
            "お腹": "服装",
            "胸": "上半身",
            "キス": "親密な接触",
            "マッサージ": "ケア",
            "痴態": "失態",
            "だらしない声": "気の抜けた反応",
            "性的": "親密",
            "エッチな": "親密な",
            "エッチ": "親密",
            "いやらし": "過剰な",
            "ロリコン": "特殊な好み",
            "ロリ": "小柄な",
            "小学生": "幼く見える",
            "幼女": "小さな子",
            "児童": "子供",
            "むにゅ": "ぶつかり",
            "ぷにぷに": "柔らかい",
            "むにっ": "ぶつかり",
            "柔らか": "やわらかい",
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)

        DROP_LINE = re.compile(
            r'股間|太もも|下半身|肌色|裸身|痴漢|盗撮|淫ら|特殊な好み.*特殊な好み'
        )
        kept = []
        for line in text.splitlines():
            if DROP_LINE.search(line):
                kept.append("")
            else:
                kept.append(line)
        text = "\n".join(kept)

        text = re.sub(r"十七年ほど生きてきて", "これまで生きてきて", text)
        text = re.sub(r"(小学|中学)(生|校)", "年下の子", text)
        return text

    def _manifest_chapters(self) -> List[Dict[str, Any]]:
        """Return normalized chapter list from manifest."""
        chapters = self.manifest.get("chapters", [])
        if not chapters:
            chapters = self.manifest.get("structure", {}).get("chapters", [])
        return chapters if isinstance(chapters, list) else []

    def _required_chapter_ids(self) -> List[str]:
        """Return chapter IDs that should appear in Section 3 timeline."""
        chapter_ids: List[str] = []
        for idx, chapter in enumerate(self._manifest_chapters(), start=1):
            if not isinstance(chapter, dict):
                continue
            chapter_id = str(chapter.get("id", "")).strip() or f"chapter_{idx:02d}"
            chapter_ids.append(chapter_id)
        return chapter_ids

    def _extract_timeline_ids_from_brief(self, brief_text: str) -> List[str]:
        """Extract chapter timeline headings from brief markdown."""
        section_match = re.search(
            r"^##\s+3\.\s+CHAPTER-BY-CHAPTER TIMELINE\s*$([\s\S]*?)(?=^##\s+4\.|\Z)",
            brief_text,
            flags=re.MULTILINE,
        )
        section_text = section_match.group(1) if section_match else brief_text
        headings = re.findall(r"^###\s+([^\n]+)$", section_text, flags=re.MULTILINE)
        return [h.strip() for h in headings if h.strip()]

    def _current_cache_meta(self, prequel_audit: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build cache metadata snapshot for invalidation checks."""
        chapter_ids = self._required_chapter_ids()
        chapter_files: List[Dict[str, Any]] = []
        for chapter in self._manifest_chapters():
            if not isinstance(chapter, dict):
                continue
            cid = str(chapter.get("id", "")).strip()
            jp_file = str(chapter.get("jp_file") or chapter.get("source_file") or "").strip()
            src = self.work_dir / "JP" / jp_file if jp_file else None
            exists = bool(src and src.exists())
            chapter_files.append(
                {
                    "id": cid,
                    "jp_file": jp_file,
                    "exists": exists,
                    "size": int(src.stat().st_size) if exists else 0,
                    "mtime_ns": int(src.stat().st_mtime_ns) if exists else 0,
                }
            )
        payload = {
            "version": 1,
            "model": self.model,
            "target_language": self.target_language,
            "chapter_ids": chapter_ids,
            "chapter_files": chapter_files,
            "generated_at": time.time(),
        }
        payload["prequel_brief_injection"] = self._prequel_cache_signature(prequel_audit)
        return payload

    def _load_cache_meta(self) -> Optional[Dict[str, Any]]:
        """Load brief cache metadata sidecar if available."""
        if not self.brief_meta_path.exists():
            return None
        try:
            with open(self.brief_meta_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            return payload if isinstance(payload, dict) else None
        except Exception as e:
            logger.debug(f"[BRIEF] Failed reading cache metadata: {e}")
            return None

    def _save_cache_meta(self, meta: Dict[str, Any]) -> None:
        """Persist brief cache metadata sidecar."""
        try:
            with open(self.brief_meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[BRIEF] Failed saving cache metadata: {e}")

    def _backup_existing_brief(self) -> None:
        """Backup current brief before regeneration."""
        if not self.brief_path.exists():
            return
        backup_path = self.context_dir / "TRANSLATION_BRIEF_backup.md"
        try:
            backup_path.write_text(self.brief_path.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info(f"[BRIEF] Backed up previous brief → {backup_path.name}")
        except Exception as e:
            logger.warning(f"[BRIEF] Failed to backup previous brief: {e}")

    def _validate_cached_brief(
        self,
        brief_text: str,
        cache_meta: Optional[Dict[str, Any]],
        expected_prequel_signature: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """
        Validate cached brief against current manifest/corpus signature.

        Returns:
            (is_valid, reason)
        """
        required_ids = self._required_chapter_ids()
        if not required_ids:
            return True, "manifest has no chapters"

        required_set = {cid.lower() for cid in required_ids}
        timeline_set = {cid.lower() for cid in self._extract_timeline_ids_from_brief(brief_text)}
        missing = sorted(required_set - timeline_set)
        if missing:
            preview = ", ".join(missing[:5])
            return False, f"timeline missing chapter IDs: {preview}"

        if expected_prequel_signature is not None:
            if cache_meta is None:
                return False, "missing cache metadata for prequel continuity signature"
            cached_prequel_signature = cache_meta.get("prequel_brief_injection")
            if cached_prequel_signature != expected_prequel_signature:
                return False, "prequel continuity signature changed"

        if cache_meta is None:
            return True, "no cache metadata (timeline coverage valid)"

        cached_lang = (cache_meta.get("target_language") or "").lower().strip()
        current_lang = self.target_language.lower().strip()
        if cached_lang and cached_lang != current_lang:
            return False, f"target_language changed ({cached_lang} → {current_lang})"

        meta_ids = cache_meta.get("chapter_ids", [])
        if isinstance(meta_ids, list):
            meta_set = {str(v).strip().lower() for v in meta_ids if str(v).strip()}
            if meta_set and meta_set != required_set:
                return False, "cached metadata chapter set mismatch"

        current_files = self._current_cache_meta().get("chapter_files", [])
        meta_files = cache_meta.get("chapter_files", [])
        if isinstance(meta_files, list) and meta_files:
            current_sig = [
                (
                    str(row.get("id", "")),
                    str(row.get("jp_file", "")),
                    int(row.get("size", 0)),
                    int(row.get("mtime_ns", 0)),
                )
                for row in current_files
            ]
            cached_sig = [
                (
                    str(row.get("id", "")),
                    str(row.get("jp_file", "")),
                    int(row.get("size", 0)),
                    int(row.get("mtime_ns", 0)),
                )
                for row in meta_files
            ]
            if cached_sig != current_sig:
                return False, "source chapter file signature changed"

        return True, "valid"


# ── Standalone entry point ────────────────────────────────────────────────────

def main() -> None:
    """
    Subprocess entry point for Phase 1.56.

    Usage:
        python -m pipeline.post_processor.translation_brief_agent --volume <vol_id> [--force]
    """
    import argparse
    import json
    import sys

    # Ensure subprocess INFO logs are visible when launched from mtl.py.
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        force=True,
    )

    parser = argparse.ArgumentParser(
        description="Phase 1.56: Generate Translator's Guidance Brief for a volume."
    )
    parser.add_argument("--volume", required=True, help="Volume ID (directory name inside WORK/)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-generate even if a cached brief already exists",
    )
    parser.add_argument(
        "--enable-prequel-brief-injection",
        action="store_true",
        help="Inject prequel volume TRANSLATION_BRIEF.md into Phase 1.56 prompt when sequel is detected",
    )
    args = parser.parse_args()
    logger.info(
        f"[BRIEF] Subprocess started for volume='{args.volume}' force={args.force}"
    )

    # Bootstrap pipeline environment
    try:
        from pipeline.config import WORK_DIR
        from pipeline.common.anthropic_client import AnthropicClient
        from pipeline.translator.config import (
            get_anthropic_config,
            get_phase2_openrouter_route,
            get_translation_config,
        )
    except ImportError as _e:
        logger.error(f"[BRIEF] Failed to import pipeline modules: {_e}")
        sys.exit(1)

    volume_dir = WORK_DIR / args.volume
    if not volume_dir.exists():
        logger.error(f"[BRIEF] Volume directory not found: {volume_dir}")
        sys.exit(1)

    manifest_path = volume_dir / "manifest.json"
    if not manifest_path.exists():
        logger.error(f"[BRIEF] No manifest.json found for volume: {args.volume}")
        logger.error("  Please run Phase 1 and Phase 1.5 first.")
        sys.exit(1)

    try:
        with open(manifest_path, "r", encoding="utf-8") as _f:
            manifest = json.load(_f)
    except Exception as _e:
        logger.error(f"[BRIEF] Failed to load manifest: {_e}")
        sys.exit(1)
    logger.info(
        f"[BRIEF] Manifest loaded: {manifest_path.name}, "
        f"{len(manifest.get('chapters', [])) or len(manifest.get('structure', {}).get('chapters', []))} chapters listed"
    )

    trans_config = get_translation_config()
    anthropic_cfg = get_anthropic_config()
    route_cfg = get_phase2_openrouter_route()

    model = str(
        trans_config.get("phase1_56_model")
        or "anthropic/claude-sonnet-4"
    ).strip() or "anthropic/claude-sonnet-4"

    route_base = str(route_cfg.get("base_url") or "https://openrouter.ai/api/v1").strip().rstrip("/")
    openrouter_endpoint = route_base
    api_key_env = str(route_cfg.get("api_key_env") or "OPENROUTER_API_KEY").strip() or "OPENROUTER_API_KEY"
    api_key = os.getenv(api_key_env)

    logger.info(
        "[BRIEF] Initialising Anthropic client via OpenRouter (model=%s, endpoint=%s, api_key_env=%s)",
        model,
        openrouter_endpoint,
        api_key_env,
    )

    if not api_key:
        logger.error(f"[BRIEF] Missing OpenRouter API key env var: {api_key_env}")
        sys.exit(1)

    try:
        anthropic_client = AnthropicClient(
            api_key=api_key,
            model=model,
            enable_caching=bool((anthropic_cfg.get("caching") or {}).get("enabled", True)),
            use_env_key=False,
            api_key_env=api_key_env,
            base_url=openrouter_endpoint,
        )
        anthropic_client.set_cache_ttl(int((anthropic_cfg.get("caching") or {}).get("ttl_minutes", 5) or 5))
    except Exception as _e:
        logger.error(f"[BRIEF] Failed to initialise Anthropic client via OpenRouter: {_e}")
        sys.exit(1)

    brief_agent = AnthropicTranslationBriefAgent(
        anthropic_client=anthropic_client,
        work_dir=volume_dir,
        manifest=manifest,
        target_language=manifest.get("metadata", {}).get("target_language") or "en",
        book_type=manifest.get("metadata", {}).get("book_type"),
        model=model,
        translation_config=trans_config,
        enable_prequel_brief_injection=(True if args.enable_prequel_brief_injection else None),
    )

    result = brief_agent.generate_brief(force=args.force)

    if result.success:
        action = "Loaded from cache" if result.cached else "Generated"
        logger.info(
            f"[BRIEF] ✓ {action}: {len(result.brief_text):,} chars → {result.brief_path}"
        )
        sys.exit(0)
    else:
        logger.error(f"[BRIEF] ✗ Brief generation failed: {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
