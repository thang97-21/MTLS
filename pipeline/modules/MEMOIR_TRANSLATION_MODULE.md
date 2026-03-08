# MEMOIR / NON-FICTION TRANSLATION MODULE

**Applies to:** book_type = memoir | biography | autobiography | non_fiction | essay
**Replaces:** MEGA_CHARACTER_VOICE_SYSTEM, Library_LOCALIZATION_PRIMER, ANTI_TRANSLATIONESE
**Status:** Active

---

## PART 1: FUNDAMENTAL DIFFERENCE FROM FICTION

This is a **real-person memoir**, not a light novel. The following LN-specific systems DO NOT APPLY:

- ❌ PAIR_ID honorific progression (no romance arc to track)
- ❌ Character archetypes (tsundere, gyaru, kuudere — these are fictional templates)
- ❌ Dual-signal gate for romantic register
- ❌ Tsundere oscillation tracking
- ❌ Fictional inner-monologue formatting conventions

The narrator is a real person writing about their real life. Translate their voice, not a character archetype.

---

## PART 2: FIRST-PERSON VOICE CONSISTENCY

### Core Rule
The narrator's first-person voice is the single most important element. It must remain consistent across all chapters.

**Identify the narrator's register at the opening chapter and lock it:**
- Introspective / literary prose → maintain elevated register throughout
- Casual / conversational → maintain casual register throughout
- Mixed (literary narration + casual dialogue) → maintain the distinction; do not flatten

### Self-Reference
The narrator's self-reference pronoun is fixed for the entire work. Do not shift it based on scene context.

- Identify the JP self-reference (私, 僕, あたし, etc.) in the opening chapter
- Lock the target-language equivalent for the full work
- Exception: if the narrator explicitly shifts self-reference to mark a life-stage transition (e.g., childhood vs. adult self), mirror that shift

### Address to Reader
Many memoirs address the reader directly. Maintain the register of that address consistently:
- Formal address → keep formal throughout
- Intimate address (ねぇ, あなた) → keep intimate throughout

---

## PART 3: REAL-WORLD ENTITY HANDLING

### Locked Entities — Do Not Translate
The following categories must be preserved verbatim or romanized, never translated:

| Category | Rule | Example |
|----------|------|---------|
| Venue names | Preserve romanized | Zepp DiverCity, 国立競技場 → Kokuritsu Kyogijo |
| Company / label names | Preserve as-is | CloudNine, KADOKAWA, Universal Music |
| Platform names | Preserve as-is | NicoNico, YouTube, Twitter/X |
| Song titles | Preserve JP title + romanization on first mention | うっせぇわ (Usseewa) |
| Album titles | Same as song titles | 狂言 (Kyogen) |
| Tour names | Preserve JP + romanization | Wish, 心臓 (Shinzo) |
| Real person names | Use established romanization | Ado, Chigira Takuya |

### Dates and Numbers
Real dates are factual anchors. Translate format but preserve the date exactly:
- 2019年9月17日 → September 17, 2019 (EN) / ngày 17 tháng 9 năm 2019 (VN)
- Do not approximate or paraphrase dates

---

## PART 4: STRUCTURAL ELEMENTS

### Editor Footnotes
Footnotes marked with ＊ or （＊）are editor annotations, not part of the narrator's voice.

**Format rule:** Preserve footnote markers and content. Translate the footnote text but keep it clearly distinct from the main narrative. Do not merge footnote content into the prose.

```
Source:  アクターズスクール（＊）
         ＊アクターズスクール　歌唱・ダンス・演技など…

Target:  Acting school (＊)
         ＊Acting school: A training institution covering singing, dance, acting…
```

### Ruby / Furigana
Ruby text provides pronunciation for difficult kanji. Handle consistently:
- If the target language uses romanization: render as `word (reading)` on first occurrence, then drop
- If the target language is phonetic (VN): the reading is usually redundant — drop unless the kanji meaning is ambiguous

### Song Lyrics
Lyrics embedded in memoir prose are the narrator's own creative work. They require distinct formatting and artist-specific aesthetic constraints.

**Detection signals:**
- Line breaks within a paragraph
- Rhyme or rhythmic structure
- Quotation marks around multi-line content
- Context: narrator is playing guitar, recording, or performing

**Formatting rule:** Preserve line breaks exactly. Do not reflow lyrics into prose. Translate with attention to rhythm and emotional register — lyrics are not prose and should not read as prose.

```
Source:
傷つけて、傷つけて　報われようとしているのか？
「幸せになれる……！」とか？笑

Target (preserve line breaks):
Hurt me, hurt me — is that how I earn my reward?
"I can be happy…!" or something? lol
```

**⚠ AESTHETIC CONSTRAINT MODULE — REQUIRED LOADING**

The two rules above govern formatting only. They do not govern register, word choice, or transcreation fidelity. Default model aesthetic preferences (polish, elevation, smoothing) will produce incorrect outputs for most songs in this memoir.

The lyric constraint system is a two-layer stack:

**Layer 1 — Universal scaffold (series-agnostic):**
```
pipeline/modules/LYRIC_RHYTHM_SCAFFOLD.json
```
Contains the Rhythm Read Protocol (5-step pre-translation mode classification), two mandate modes (RAW / RHYTHM), global prohibitions GP-01–GP-07, full taxonomy, ICL library with Vivarium examples as calibration anchors, and mode decision matrix. Applies to any project.

**Layer 2 — Vivarium application layer (this series):**
```
pipeline/modules/MUSIC_LYRICS_AESTHETIC.json
```
Extends the scaffold with Vivarium-specific song entries, required word/construction choices for all 12+ named songs, reference anchors RA-01–RA-09 from the actual fix pass, and artist taxonomy mapped to the scaffold's RAW/RHYTHM modes. When translating Vivarium, load this file — it inherits and supersedes the scaffold for song-specific decisions.

The key design principle: all constraints are prohibitions and mandates (DO NOT / MUST), not aesthetic descriptions (be raw / be aggressive). Structural prohibitions override RLHF aesthetic defaults. Aesthetic descriptions do not.

### Social Media Posts / DMs
Quoted social media content (Twitter posts, DMs) has its own register — informal, abbreviated, emotionally raw. Do not formalize.

**Format rule:** Preserve bold formatting (＊＊text＊＊) used to mark quoted posts. Translate the content but keep the informal register.

---

## PART 5: REGISTER MANAGEMENT

### Two-Register System
Memoirs typically operate in two registers simultaneously:

**Narrative register** (introspective, literary):
- Describes scenes, emotions, reflections
- May be elevated and poetic
- Translate with full literary attention

**Dialogue register** (naturalistic, character-specific):
- Quotes from real people in the narrator's life
- Each person has a distinct speech pattern
- Preserve register differences between speakers

### Temporal Shifts
Memoirs frequently shift between past and present tense. Mirror the tense structure of the source:
- Past narration → past tense in target
- Present-tense reflection (narrator commenting from now) → present tense in target
- Do not normalize all narration to a single tense

---

## PART 6: WHAT REPLACES THE PAIR_ID SYSTEM

For memoirs, the equivalent of PAIR_ID is **relationship register** — how the narrator addresses and refers to each real person in their life.

**Identify per relationship:**
- Family (parents, siblings): formal/intimate family address
- Mentors / industry figures: respectful but not stiff
- Peers / friends: casual, warm
- Strangers / public: neutral

**Lock the register per relationship** and maintain it consistently. If the narrator's relationship with a person evolves (e.g., a manager becomes a trusted mentor), mirror that evolution in the address register — but only when the source text signals it explicitly.

---

## PART 7: ANTI-PATTERNS FOR MEMOIR

❌ **Do not apply fictional character voice templates** to real people quoted in the memoir.

❌ **Do not add honorific suffixes** (-san, -kun) to real people's names unless the source uses them.

❌ **Do not translate venue/platform/song names** — these are proper nouns and cultural anchors.

❌ **Do not flatten the two-register system** — literary narration and casual dialogue must remain distinct.

❌ **Do not reflow lyrics into prose** — line breaks in lyrics are structural, not decorative.

❌ **Do not infer romantic subtext** where none exists — memoir relationships are professional, familial, or platonic unless the narrator explicitly states otherwise.

---

**END OF MODULE**
**Status:** Active
**Last updated:** 2026-02-26
