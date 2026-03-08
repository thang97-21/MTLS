# FANTASY TRANSLATION MODULE (FFXVI Method)

**Version:** 2.0
**Date:** 2026-02-08
**Purpose:** Fantasy-specific translation framework for light novels with Western medieval/fantasy settings
**Based On:** Final Fantasy XVI English localization (Michael-Christopher Koji Fox method)
**Hardened By:** 25d9 audit (Lord Marksman and Vanadis Vol 1) — 89.0/100, Grade A-
**Genre:** Fantasy romance, isekai, noble academy, sword & sorcery

---

## Table of Contents

1. [Core Philosophy](#core-philosophy)
2. [Fantasy Register System](#fantasy-register-system)
3. [Character Archetypes (Fantasy)](#character-archetypes-fantasy)
4. [Contraction Rules (Fantasy Override)](#contraction-rules-fantasy-override)
5. [Honorifics & Titles](#honorifics-titles)
6. [Japanese Interjection Adaptation](#japanese-interjection-adaptation)
7. [World-Building Terminology](#world-building-terminology)
8. [Anti-Victorian Guardrails](#anti-victorian-guardrails)
9. [Name Consistency Protocol](#name-consistency-protocol) *(V2.0)*
10. [POV Consistency Enforcement](#pov-consistency) *(V2.0)*
11. [Cultural Term Preservation](#cultural-term-preservation) *(V2.0)*
12. [Battle Choreography](#battle-choreography) *(V2.0)*
13. [Multi-Volume Continuity](#multi-volume-continuity) *(V2.0)*
14. [Chunk Boundary Awareness](#chunk-boundary-awareness) *(V2.0)*

---

<a name="core-philosophy"></a>
## 1. Core Philosophy: Modern Fantasy Register

> **25d9 VALIDATION:** This philosophy scored 82/100 prose quality and 8.8/10 voice differentiation across 15 chapters. The three pillars WORK — no changes needed at the philosophy level.

**Definition:** Modern fantasy register is **refined but accessible** — it sounds timeless without being archaic, elegant without being stuffy.

**The FFXVI Principle:**
> "Characters should sound like people from a fantasy world, not actors performing Shakespeare."

### Three Pillars

#### Pillar 1: ELEGANCE THROUGH WORD CHOICE, NOT GRAMMAR RIGIDITY

| ❌ Victorian Rigidity | ✅ FFXVI-Style Elegance | 🎯 Why It Works |
|----------------------|------------------------|------------------|
| "I do not believe that to be wise." | "I don't think that's wise." | Contraction doesn't reduce elegance |
| "Can you not see that I am occupied?" | "Can't you see I'm busy?" | Natural inversion, modern flow |
| "I shall take my leave, if you will excuse me." | "I'll take my leave." | Shorter = more confident |
| "I am entirely serious about this matter." | "I'm serious." | Directness = emotional weight |

**Rule:** Use **sophisticated vocabulary**, not **archaic grammar**, to convey nobility.

---

#### Pillar 2: PERSONALITY OVER PROTOCOL

**Japanese source:** ですます調 (desu-masu formal ending)
**Bad translation:** Translate formality → Victorian grammar
**FFXVI approach:** Translate formality → CHARACTER PERSONALITY

| Character Type | Japanese | ❌ Victorian | ✅ FFXVI Style |
|---------------|----------|--------------|----------------|
| Loyal Servant | 「お嬢様、準備が整いました」 | "My lady, the preparations have been completed." | "My lady, we're ready." |
| Tsundere Princess | 「別に気にしてないわよ」 | "I am not particularly concerned about it." | "I'm not worried about it." |
| Stoic Knight | 「承知しました」 | "I have understood your command." | "Understood." |

**Rule:** Let PERSONALITY drive formality, not rigid grammar rules.

---

#### Pillar 3: EMOTIONAL DIRECTNESS

**Japanese politeness:** 包み込む (tsutsumi-komu) = wrap feelings in politeness
**Fantasy English:** UNWRAP the feeling, express directly

| ❌ Over-Polite Wrapper | ✅ Direct Fantasy English | 🎯 Emotion |
|-----------------------|---------------------------|------------|
| "I would be grateful if you could answer me without reservation." | "Please, be honest with me." | Vulnerability |
| "I find myself experiencing a certain degree of unease." | "I'm uneasy." | Anxiety |
| "It would bring me great joy to hear of your acceptance." | "I'd be happy if you'd accept." | Hope |

**Rule:** Fantasy characters express emotions **directly**, not through layers of politeness.

---

<a name="fantasy-register-system"></a>
## 2. Fantasy Register System

### EPS Still Applies, But With Fantasy Adjustments

**Standard EPS Scale:** 1.0 (strangers) → 5.0 (lovers)

**Fantasy Modification:**
- **Base formality is LOWER** than modern Japanese settings
- **Contractions allowed at ALL levels** (even EPS [COLD])
- **Title usage** determines formality, not grammar rigidity

---

### Formality Tiers (Fantasy)

#### Tier 1: CEREMONIAL (EPS [COLD], formal ceremonies only)

**When to use:**
- Royal proclamations
- Knighting ceremonies
- Formal trials/judgments

**Characteristics:**
- Full forms allowed (but not required)
- Elevated vocabulary
- Passive voice acceptable

**Example:**
```
"By the authority vested in me, I hereby grant you the title of knight."
```

---

#### Tier 2: RESPECTFUL (EPS [COLD]-2.5, servant-noble, student-teacher)

**When to use:**
- Servant addressing noble
- Knight addressing commander
- Student addressing instructor

**Characteristics:**
- ✅ Contractions allowed: "don't," "can't," "won't"
- ✅ Title + name: "Lady Elen," "Count Tigrevurmud"
- ✅ Polite vocabulary without stiffness
- ❌ No Victorian inversions: NOT "can you not," NOT "I shall"

**Example — Servant to Noble:**
```
"Lady Elen, I don't think that's wise."
"My lady, I've finished the preparations."
"I'm honored to serve you."
```

---

#### Tier 3: FAMILIAR (EPS [NEUTRAL]-4.0, friends, comrades)

**When to use:**
- Fellow knights
- Battlefield comrades (Tigre and Rurick)
- Close servants/nobles with bond

**Characteristics:**
- Full contraction freedom
- Casual vocabulary while maintaining setting
- Direct emotion expression
- Optional title dropping (if close)

**Example:**
```
"You're worrying too much."
"I'm not letting you do this alone."
"Don't be ridiculous."
```

---

#### Tier 4: INTIMATE (EPS [HOT]-5.0, lovers, family)

**When to use:**
- Romantic partners (Tigre and Elen)
- Siblings
- Parent-child

**Characteristics:**
- Full casual English (within fantasy vocabulary)
- Emotional vulnerability
- Pet names acceptable
- Shortest sentence forms

**Example — Romantic:**
```
"I love you."
"Don't leave me."
"You're everything to me."
```

---

<a name="character-archetypes-fantasy"></a>
## 3. Character Archetypes (Fantasy)

### Archetypes for Fantasy Settings

These replace/augment modern archetypes when `WORLD_SETTING = FANTASY`:

---

#### ARCHETYPE: LOYAL_SERVANT

**Profile:** Devoted attendant to nobility. Warm formality, not robotic. Uses contractions naturally. Shows personality within duty.

**Vocabulary:** "My lady/lord" · "Of course" · "I'll handle it" · "As you wish"
**Rhythm:** Legato (L) — flowing, composed

**Example Voice:**
```
"Lady Elen, I've brought your tea."
"I don't mind at all, my lady."
"You're overworking yourself again."
```

**AVOID:** "If you will excuse me" ❌ · "I am humbled" ❌ · "That is quite admirable" ❌

---

#### ARCHETYPE: TSUNDERE_PRINCESS

**Profile:** Noble with defensive pride. Sharp tongue, soft heart. Uses contractions when flustered. Maintains dignity while showing emotion.

**Vocabulary:** "Hmph" · "Honestly" · "Don't misunderstand" · "It's not like..."
**Rhythm:** Staccato (S) — clipped, defensive

**Example Voice:**
```
"Can't you see I'm busy?"
"I'm not worried about you!" (lying)
"Don't get the wrong idea."
```

**AVOID:** "Can you not see..." ❌ · "I am not particularly concerned..." ❌ · Victorian inversions ❌

---

#### ARCHETYPE: STOIC_KNIGHT

**Profile:** Battle-hardened warrior. Minimal words, maximum impact. Direct speech, no flowery language. Protective instinct.

**Vocabulary:** "Understood" · "Leave it to me" · "Stay behind me" · "I won't let them"
**Rhythm:** Tenuto (T) — weighted, deliberate

**Example Voice:**
```
"I'll protect you."
"Don't worry."
"They won't touch you."
```

**AVOID:** "I shall ensure your safety" ❌ · "You need not concern yourself" ❌ · Over-explanation ❌

---

#### ARCHETYPE: FRONTIER_NOBLE

> **25d9 MATCH:** Tigrevurmud Vorn — Count of Alsace, practical archer-noble from the borderlands

**Profile:** Practical noble from border regions. Direct communication style. Elegant but not pretentious. Action-oriented.

**Vocabulary:** "Indeed" · "Naturally" · "Let's move" · "I'll handle this"
**Rhythm:** Tenuto (T) — firm, confident

**Example Voice:**
```
"We don't have time for ceremony."
"I'll do what's necessary."
"That's unacceptable."
```

---

#### ARCHETYPE: COURT_NOBLE

**Profile:** High society, politically savvy. Formal but not stiff. Elegant phrasing. Uses contractions in private.

**Vocabulary:** "Indeed" · "Quite" · "I dare say" · "Naturally"
**Rhythm:** Legato (L) — flowing, refined

**Example Voice (PUBLIC):**
```
"How delightful to see you."
"That would be most unwise."
"I'm afraid I must decline."
```

**Example Voice (PRIVATE):**
```
"Don't be foolish."
"I'm worried about you."
"You're impossible."
```

---

#### ARCHETYPE: WAR_MAIDEN *(V2.0)*

> **25d9 MATCH:** Eleonora Viltaria (Elen) — Vanadis war princess wielding Arifar

**Profile:** Female warrior of noble rank. Commands armies. Fierce in battle, warm in private. Alternates between authority and vulnerability.

**Vocabulary:** "Stand your ground" · "Follow me" · "Not bad" · "Don't hold back"
**Rhythm:** Tenuto→Legato shift (battle→private)

**Example Voice (BATTLE):**
```
"Don't fall behind!"
"I'll cut through them."
"You call that a challenge?"
```

**Example Voice (PRIVATE):**
```
"You're the first person who's made me feel this way."
"I'm not as strong as you think."
"Stay with me."
```

---

<a name="contraction-rules-fantasy-override"></a>
## 4. Contraction Rules (Fantasy Override)

### THE GOLDEN RULE: CONTRACTIONS ARE ALWAYS ALLOWED IN FANTASY

**Rationale:** FFXVI proves that nobles, servants, and royalty can use contractions without losing elegance. Formality comes from **vocabulary and tone**, not grammar rigidity.

### Contraction Usage by EPS

| EPS Level | Contraction Frequency | Example |
|------------|----------------------|---------|
| 1.0-1.5 (Ceremonial) | 50% (formal moments) | "I don't know" OR "I do not know" (both valid) |
| 1.5-2.5 (Respectful) | 80% (default contractions) | "I don't think that's wise" ✅ |
| 2.5-4.0 (Familiar) | 95% (full contractions) | "You're overthinking this" ✅ |
| 4.0-5.0 (Intimate) | 100% (always contract) | "I'm here" ✅ |

### Common Contractions (Fantasy-Approved)

| Full Form | Contracted | Fantasy-Appropriate Context |
|-----------|-----------|----------------------------|
| I am | I'm | ALL contexts |
| I will | I'll | ALL contexts |
| I would | I'd | ALL contexts |
| You are | You're | ALL contexts |
| Do not | Don't | ALL contexts |
| Cannot | Can't | ALL contexts |
| Will not | Won't | ALL contexts |
| I have | I've | ALL contexts |
| That is | That's | ALL contexts |

### Exception: Emphasis

**Rule:** Use full form for EMPHASIS, not formality.

```
"I will NOT allow this." ✅ (emphasis on refusal)
"I won't allow this." ✅ (normal statement)
```

---

<a name="honorifics-titles"></a>
## 5. Honorifics & Titles

### THE ABSOLUTE RULE: NO JAPANESE HONORIFIC SUFFIXES IN OUTPUT

> **This is a hard ban, not a guideline.** Any Japanese suffix leaking into English prose — "-sama", "-san", "-kun", "-chan", "-sensei", "-dono", etc. — is a critical error that shatters fantasy immersion.

**BANNED in all fantasy English output:**
- ❌ "-sama" → "Leon-sama" → use role-appropriate English address
- ❌ "-san" → "Leon-san" → use first name or role title
- ❌ "-kun" / "-chan" → use first name or relationship term
- ❌ "-dono" → "Leon-dono" → use "Sir [Name]"
- ❌ "-sensei" → "Leon-sensei" → use "Master" or "Instructor [Name]"
- ❌ "ojou-sama" left untranslated → always render as "my lady" or "Lady [Name]"

**Every Japanese honorific has a required English equivalent. Use it. No exceptions.**

---

### Noble Attendant Hierarchy — Complete Mapping

This table covers all address forms for fantasy noble-academy / attendant-romance settings:

| Japanese Term | Context | ✅ Fantasy English | ❌ Never |
|--------------|---------|-------------------|---------|
| 様 (sama) | Addressing royalty or very high nobility | "Your Highness" / "Your Grace" / "Lord/Lady [Name]" | "-sama" |
| 王女様 (oujo-sama) | Third Princess being addressed | "Your Highness" / "Princess [Name]" | "Princess-sama" |
| 第三王女殿下 | Formal title of Third Princess | "Her Royal Highness, the Third Princess" | romanized suffix |
| お嬢様 (ojou-sama) | Noble daughter / young lady | "my lady" (attending) / "Lady [Name]" (others) | "ojou-sama" |
| 殿 (dono) | Knights, male nobles (formal/older) | "Sir [Name]" / "Lord [Name]" | "-dono" |
| 伯爵閣下 | Count (with formal address) | "Lord Count [Name]" / "Your Lordship" | "Count-kakka" |
| 公爵閣下 | Duke (with formal address) | "Your Grace, Duke [Name]" | "Duke-kakka" |
| 先生 (sensei) | Teacher / mentor | "Master [Name]" / "Instructor [Name]" | "-sensei" |
| 世話役 (sewaiyaku) | Attendant/caretaker role title | "attendant" / "caretaker" (third-person); omit in address | — |
| くん (kun) | Male peer, slight familiarity | First name only | "-kun" |
| ちゃん (chan) | Close affection, younger/female | First name / nickname / "dear" | "-chan" |
| さん (san) | Polite peer address | First name or "Mr./Ms. [Name]" (only if character is markedly formal) | "-san" |

---

### Attendant → Noble Address Protocol

For attendant-protagonist settings (e.g., Leon addressing Tetra, or previous charges Aira/Floria):

**Servant to Royalty (EPS [COLD]–2.5):**
```
✅ "Your Highness" — direct formal address
✅ "Princess Tetra" — name + title (semi-formal)
✅ "my lady" — intimate attendant usage (after trust builds)
❌ "Tetra-sama" / "Hime-sama" — never
```

**Noble Daughter / Former Charge (EPS [COOL]–3.5):**
```
✅ "Lady Aira" / "Lady Floria" — standard attendant address
✅ "my lady" — after bond is established
✅ "Aira" / "Floria" — only at EPS [WARM/HOT] (intimate)
❌ "Aira-san" / "Floria-sama" — never
```

**Noble Head of House (Count/Duke):**
```
✅ "My lord" / "Lord [Name]" — standard attendant address to male nobility
✅ "Your Lordship" — very formal occasions
✅ "sir" — brief, respectful shorthand
❌ "-sama" / "-dono" — never
```

**Between Noble Peers (Academy setting):**
```
✅ "Lady [Name]" / "Lord [Name]" — default noble-to-noble
✅ First name — if established close friendship (EPS [WARM/HOT])
❌ Any JP suffix — never
```

---

### Title Usage Rules

**Rule 1: CONSISTENT TITLE FORMAT**
- Format: Title + First Name (Western style)
- ✅ "Lady Elen" · "Count Tigrevurmud" · "Sir Rurick" · "Princess Tetra"
- ❌ "Elen-sama" · "Tetra-sama" · "Hime-sama" (breaks fantasy immersion)

**Rule 2: TITLE DROPPING AT HIGH EPS**
- EPS [COLD/COOL]: Always use title → "Lady Elen, I've finished."
- EPS [NEUTRAL]–4.0: Optional title → "Elen, I've finished."
- EPS [HOT]: First name only → "Elen, I love you."

**Rule 3: ATTENDANTS USE ROLE-APPROPRIATE INTIMACY**
- Formal duty: "Your Highness, I've prepared your tea."
- After trust: "my lady" (warm, personal but still respectful)
- High EPS (4.0+): First name only when alone and bonds are clear

**Rule 4: TRUNCATED HONORIFIC TRANSCREATION** *(Overrides 1:1 sentence structure fidelity)*

Japanese often truncates honorific suffixes mid-syllable to convey surprise or interruption (e.g., エレオノーラさ…？ cuts off "-sama"). Keeping the raw Japanese suffix fragment ("Eleonora-sa…?") breaks English fantasy immersion. This rule **temporarily overrides 1:1 sentence structure fidelity** to produce a natural English equivalent while preserving 100% semantic intent.

**Mechanism:** Substitute the character's **established English form of address**, truncated at a natural syllable break, using an **em-dash (—)** to signal the cut-off.

| JP Pattern | Character's EN Address | Transcreation | Narrator Follow-up |
|---|---|---|---|
| 「エレオノーラさ…？」 | "Lady Eleonora" (Lim→Elen) | "Lady Eleono—?" | "Before she could finish the name…" |
| 「〜さま…」 (generic) | "Lord/Lady [Name]" | Truncate name at syllable break + — | Adjust follow-up to reference "name" not "-ma" |
| 「〜せんせ…」 | "Professor [Name]" | "Profess—" | "Before she could finish…" |
| 「お兄ちゃ…」 | Context-dependent | "Broth—" | Adjust narrator line accordingly |

**Key constraints:**
- The truncation point must leave enough of the word to be **recognizable** to the reader
- The narrator follow-up line must be adjusted to reference the **English** form (e.g., "the name" not "-ma")
- This rule applies ONLY to mid-word honorific/address interruptions, NOT to general dialogue trailing off
- Em-dash (—) for abrupt cuts; ellipsis (…) for trailing off — these are **distinct mechanics**

> **25d9 Hardened Example:**
> - ❌ `"Eleonora-sa…?"` + `Before she could finish the "-ma"`
> - ✅ `"Lady Eleono—?"` + `Before she could finish the name`

---

<a name="japanese-interjection-adaptation"></a>
## 6. Japanese Interjection Adaptation

### THE RULE: NO DIRECT JAPANESE IN WESTERN FANTASY

| Japanese | ❌ Anime Dub | ✅ Fantasy English | Context |
|----------|-------------|-------------------|---------|
| え？ (e?) | "Eh?" | "Hm?" / "What?" / "Pardon?" | Surprise/confusion |
| あ (a) | "Ah" | "Oh" / "Ah" (acceptable) | Realization |
| あら (ara) | "Ara?" | "Oh?" / "My" | Refined surprise (noble women) |
| おい (oi) | "Oi!" | "Hey!" / "You there!" | Calling attention |
| うん (un) | "Nn" | "Mm" / "Mhm" | Agreement |
| ふふ (fufu) | "Fufu" | "Heh" / soft laugh | Amusement |
| ちっ (chi) | "Tch!" | "Tsk!" / "Damn!" | Frustration |
| はぁ (haa) | "Haa" | Sigh / "Ugh" | Exasperation |

---

<a name="world-building-terminology"></a>
## 7. World-Building Terminology

### Handling Fantasy-Specific Terms

**Rule 1: PRIORITIZE ENGLISH EQUIVALENTS**

| Japanese Concept | English Equivalent |
|-----------------|-------------------|
| 学園 (gakuen) | Academy |
| 騎士団 (kishidan) | Knight Order / Knighthood |
| 魔法学院 (mahou gakuin) | School of Magic / Arcane Academy |
| 冒険者ギルド | Adventurer's Guild |

**Rule 2: KEEP UNIQUE PROPER NOUNS** — Character names, place names, weapon names from manifest stay romanized.

**Rule 3: CONSISTENCY** — Once you establish a term, STICK TO IT. Never alternate between different translations of the same concept.

> **25d9 Example:** "Zhcted" must always be "Zhcted" — never "Zcted" or "Zchted". "Vanadis" never becomes "War Maiden" mid-text once established.

---

<a name="anti-victorian-guardrails"></a>
## 8. Anti-Victorian Guardrails

> **25d9 VALIDATION:** Zero catastrophic Victorian leaks across 15 chapters. These guardrails work.

### Victorian Red Flags — Detection & Fix

| # | Victorian Flag | ❌ Example | ✅ Fix |
|---|---------------|-----------|--------|
| 1 | "I shall" / "You shall" | "I shall return presently." | "I'll return shortly." |
| 2 | "Can you not" / "Do you not" | "Can you not see I am occupied?" | "Can't you see I'm busy?" |
| 3 | "If you will excuse me" | "If you will excuse me, I shall take my leave." | "Excuse me, I'll take my leave." |
| 4 | "I am humbled" | "I am humbled by your praise." | "I'm honored." / "Thank you." |
| 5 | "That is quite [adj]" | "That is quite admirable." | "That's impressive." |
| 6 | Passive voice overuse | "The preparations have been completed." | "We're ready." |

**"Shall" is ONLY acceptable in:**
- Royal decrees: "You shall be knighted."
- Formal oaths: "I shall serve faithfully."
- Emphasis/threat: "You shall regret this."

**Rule:** NEVER use negative inversion. Use contractions with normal word order.
**Rule:** Use active voice. Make characters AGENTS, not observers.

---

---

# V2.0 ADDITIONS — Post-25d9 Audit Hardening

> The following sections were added after the 25d9 volume audit (Lord Marksman and Vanadis). They address the specific vulnerability classes that the FFXVI Method V1.0 did not cover.

---

<a name="name-consistency-protocol"></a>
## 9. Name Consistency Protocol *(V2.0)*

> **25d9 LESSON:** 477 name variants were detected across 15 chapters. Ambiguous JP romanizations (ティグルヴルムド → Tigrevurmud/Tigrevrumud/Tigruvrmud) compound exponentially: N ambiguous names × M chapters = N×M drift vectors.

### The Canonical Name Rule

**ONCE A NAME IS ESTABLISHED IN THE MANIFEST, IT IS IMMUTABLE.**

The pipeline's `manifest.json` contains a `character_names` mapping. Every name variant MUST resolve to the canonical form before output.

### Common Drift Patterns in Fantasy

| Drift Type | Example | Prevention |
|-----------|---------|------------|
| Vowel swap | Elen → Ellen, Mila → Mira | Lock exact spelling from Ch01 |
| Consonant cluster | Tigrevurmud → Tigrevrumud | Copy-paste from manifest |
| Prefix/suffix | Silvfrau → Silver Frauen | Treat as atomic proper noun |
| Romanization variant | Zhcted → Zcted, Zchted | Glossary lock enforcement |
| Nickname inconsistency | Tigre → Tiger, Tigr | Lock nickname too |

### Rules

1. **Chapter 1 establishes canon.** All names from the manifest MUST appear correctly in Ch01. The pipeline validates this.
2. **Cross-chapter inheritance.** Each chapter receives the canonical name list in its prompt context. Never re-romanize from Japanese.
3. **Compound names are atomic.** "Tigrevurmud Vorn" is ONE unit — never split or re-romanize parts independently.
4. **Nicknames are separate entries.** "Tigre" (nickname) and "Tigrevurmud" (full name) are both locked independently.
5. **Place names follow the same rules.** "Olmütz," "Alsace," "Zhcted" — all immutable once established.

### Auto-Fix Behavior

The glossary lock module will automatically replace detected variants with canonical forms post-translation. The translator should still aim for correct output — auto-fix is a safety net, not a crutch.

---

<a name="pov-consistency"></a>
## 10. POV Consistency Enforcement *(V2.0)*

> **25d9 LESSON:** Chapter 02 contained a dream sequence where the translator shifted from third-person to first-person narration, likely triggered by 俺 (ore = "I") in the Japanese source appearing in a subjective passage. This required a full chapter rewrite.

### The POV Declaration Rule

**Each volume declares a narrative POV in metadata. Honor it absolutely.**

Most fantasy light novels use **third-person limited** narration. The Japanese source may contain first-person markers (俺, 僕, 私) in:
- **Dialogue** — expected, always allowed
- **Internal monologue** — render as third-person thought
- **Dream sequences** — keep third-person, use "he felt" not "I felt"

### Third-Person Enforcement Patterns

| Japanese Pattern | ❌ First-Person Leak | ✅ Third-Person Correct |
|-----------------|---------------------|------------------------|
| 俺は思った | "I thought..." | "He thought..." / "Tigre thought..." |
| 彼女の顔を見て、俺は | "Looking at her face, I..." | "Looking at her face, he..." |
| 「これは...」と俺は呟いた | "I murmured, 'This is...'" | "He murmured, 'This is...'" |
| 俺の心臓が跳ねた | "My heart leaped." | "His heart leaped." |

### Dream Sequence & Flashback Protocol

Dream sequences and flashbacks are the highest-risk zones for POV leaks because the source prose becomes more subjective.

**Rules:**
1. Maintain third-person even inside dreams
2. Use "he/she" pronouns, never "I/my/me" in narration
3. Mark dream transitions clearly: *italics* or scene break + "In the dream..."
4. Internal monologue inside dreams: use *italics* for thought, still third-person:
   - ✅ *He couldn't lose her. Not again.*
   - ❌ *I couldn't lose her. Not again.*

### Internal Monologue Convention

For third-person volumes, internal thoughts should be rendered as:
- **Indirect thought (preferred):** He wondered if she was safe.
- **Italicized direct thought (acceptable):** *Is she safe?* he wondered.
- **NEVER:** I wondered if she was safe. *(first-person leak)*

---

<a name="cultural-term-preservation"></a>
## 11. Cultural Term Preservation *(V2.0)*

> **25d9 LESSON:** The volume features a pseudo-European setting with cultural artifacts that should NOT be over-translated. The FFXVI Method V1.0 had no guidance on when to preserve cultural flavor vs. naturalize.

### The Cultural Color Rule

**When the source uses a culturally-specific term that adds world-building flavor, PRESERVE it — even if an English equivalent exists.**

### Preservation Categories

#### Category 1: FOOD & DRINK — Always Preserve Local Flavor

| Source Term | ❌ Over-Naturalized | ✅ Preserved |
|------------|--------------------|--------------| 
| chai (チャイ) | "tea" | "chai" |
| vino (ヴィーノ) | "wine" | "vino" |
| mead (ミード) | "honey wine" | "mead" |
| stew (シチュー) | "meat dish" | "stew" |

**Why:** These terms add cultural texture to the world. A character ordering "chai" feels like a different world than one ordering "tea."

#### Category 2: MILITARY TERMS — Use Established Fantasy English

| Source | Translation | Notes |
|--------|------------|-------|
| 戦姫 (Vanadis title) | "War Maiden" or "Vanadis" | Use the canonical term from manifest |
| 竜具 (dragonic tool) | Name from manifest (e.g., "Arifar") | Keep proper name |
| 騎兵 | "cavalry" | Standard military English |
| 弓兵 | "archer" | Standard military English |

#### Category 3: EXCLAMATIONS & OATHS — Adapt to Setting

| Source | ❌ Modern | ✅ Fantasy-Appropriate |
|--------|----------|----------------------|
| くそ (kuso) | "Shit!" | "Damn!" or "Blast!" |
| 神よ (kami yo) | "Oh God!" | "Gods!" or "By the gods!" |
| なんてこった | "No way!" | "What in the—" or "Impossible!" |

**Rule:** Match the exclamation to the world's religiosity and setting. Polytheistic worlds use "gods" (plural).

---

<a name="battle-choreography"></a>
## 12. Battle Choreography *(V2.0)*

> **25d9 VALIDATION:** The battle scenes in Ch04-06 and Ch09-12 were the literary high points (rated 9.2/10 by auditor). This section codifies what worked.

### The Clarity Rule

**Battle scenes must be physically clear. The reader should always know:**
1. WHERE each character is positioned
2. WHAT weapon they're using
3. HOW the action flows spatially

### Weapon Terminology Consistency

| Weapon | ✅ Consistent Term | ❌ Inconsistent Variants |
|--------|-------------------|------------------------|
| Tigre's bow | "bow" (+ "arrow" when drawing) | "longbow" / "shortbow" / alternating |
| Elen's Arifar | "Arifar" (named blade) | "her sword" / "the dragonic weapon" / "blade" — only on first reference |
| Mila's Lavias | "Lavias" (named spear) | same rule — name after introduction |

**Rule:** Name weapons using their proper names from the manifest after first introduction. A brief descriptor on first appearance is fine ("Arifar, the Silver Flash"), then use just the name.

### Battle Prose Guidelines

**DO:**
- Use strong, active verbs: "slashed," "parried," "lunged," "deflected"
- Keep sentences short during high-action moments
- Use spatial language: "closed the distance," "flanked," "retreated"
- Show physical consequences: "the impact jarred his arm"

**DON'T:**
- Use passive voice in combat: ❌ "The sword was swung"
- Over-narrate internal thoughts during fast action
- Use identical sentence structure for consecutive actions
- Describe the same action twice with different words

### Rhythm in Battle

Battle scenes should alternate between:

| Phase | Sentence Style | Example |
|-------|---------------|---------|
| Action burst | Short, punchy (5-10 words) | "Elen swung Arifar. The blade sang." |
| Tactical pause | Medium, analytical (15-25 words) | "Tigre nocked an arrow, gauging the distance to the enemy commander." |
| Aftermath | Longer, reflective (20-35 words) | "The battlefield fell silent. Around them, the snow had turned red, and the bitter smell of iron hung in the air." |

---

### Embedded Lyrics and Verse Passages

> **Scope note:** The Legato/Staccato/Tenuto system above governs **prose sentence rhythm only**. Embedded song lyrics, in-world poems, character compositions, and structured verse passages require a separate constraint set — **Lyric Transcreation Mode**.

Lyric Transcreation Mode operates on two mandates:

- **RAW mode** — for songs that are a character's own emotional expression: performer_voice, amateur_original, impulsive battle cry. Anti-refinement is maximal. Broken syntax stays broken. Intensifiers are load-bearing. The register is blunt, thrown, inside the emotion.
- **RHYTHM mode** — for songs composed by a named composer, formal motif songs, commissioned anthems, sacred/ritual texts. The composer's architectural intent is honored. Archaic register is correct. Formal staccato (each clipped line completing its own clause) is distinct from RAW staccato (lines fragmented by impulse).

**Before translating any lyric block:**
1. Execute the Rhythm Read Protocol (5-step scan: line length distribution, broken syntax, vocabulary register, composer origin, narrative function)
2. Classify as RAW or RHYTHM
3. Apply mode constraints + Global Prohibitions GP-01 through GP-07

**Taxonomy for LN/VN contexts:** The `narrative_device` type covers all in-universe lyrics (idol setlists, villain motif songs, world-building verse, opening ceremony anthems). Mode is determined by what the lyric is **doing** in the story — not just its surface register. A villain's formal motif song → RHYTHM. A protagonist's improvised battle cry → RAW.

**Load the scaffold:**

```
pipeline/modules/LYRIC_RHYTHM_SCAFFOLD.json
```

That file contains the full Rhythm Read Protocol, both mode constraint sets, ICL library (Vivarium songs as universal calibration anchors — Usseewa for RAW, Aku no Musume for RHYTHM), taxonomy definitions, and the mode decision matrix for resolving conflicting signals.

---

<a name="multi-volume-continuity"></a>
## 13. Multi-Volume Continuity *(V2.0)*

> **25d9 LESSON:** This volume had a dual-act structure (Act I: Ch01-06, Act II: Ch07-15) that functionally behaves like two volumes. Glossary drift was worst at the act boundary.

### Cross-Act Glossary Inheritance

**Rule:** When a volume has multiple acts, arcs, or parts:
1. The canonical name list from Act I carries forward to Act II
2. New characters introduced in Act II are added to the glossary, not substituted
3. The `lookback_chapters` setting must span the act boundary (minimum: last 2 chapters of previous act)

### Character Relationship Evolution

Characters' relationships evolve across a volume. The register (EPS) should shift accordingly:

| Phase | Tigre↔Elen EPS | Speech Pattern |
|-------|-----------------|----------------|
| Ch01-02 (meeting) | 2.0 (strangers) | "Lady Eleonora" / formal |
| Ch03-06 (alliance) | 3.0 (comrades) | "Elen" / familiar |
| Ch07-12 (deepening) | 4.0 (trust) | First name, emotional openness |
| Ch13-15 (resolution) | 4.5 (intimate) | Vulnerable, direct |

**Rule:** EPS shifts must be gradual and consistent. Never jump from 2.0 to 4.5 in a single chapter. Track the trajectory.

### Lookback Context Window

The pipeline provides previous chapter context to maintain continuity. Use it to:
1. Match the exact name spellings from recent chapters
2. Continue any unresolved emotional arcs
3. Maintain consistent terminology for world-building terms
4. Preserve the current EPS level for each character pair

---

<a name="chunk-boundary-awareness"></a>
## 14. Chunk Boundary Awareness *(V2.0)*

> **25d9 LESSON:** 250+ truncated sentences were found at chunk boundaries where the LLM hit its output token limit mid-paragraph. This was the #1 quality issue by volume.

### The Completion Rule

**EVERY paragraph must end with terminal punctuation (. ! ? " …)**

If you are approaching your output token limit:
1. **FINISH the current sentence** — never truncate mid-word or mid-clause
2. **End at a paragraph boundary** — not mid-paragraph
3. **Prefer ending at a scene break** (◆ or * * *) if one is nearby

### Truncation Signatures to Avoid

| Signature | Example | Severity |
|-----------|---------|----------|
| Mid-word cut | "Tigre drew his bow and" | CRITICAL |
| Trailing hyphen | "The army marched through the-" | CRITICAL |
| Dangling conjunction | "She turned to him and" | CRITICAL |
| Missing period at paragraph end | "The night was cold" (no period, blank line follows) | HIGH |
| Comma-terminated paragraph | "The soldiers retreated," (blank line follows) | HIGH |

### What the Pipeline Does

The truncation validator will flag these patterns and may block the chapter if CRITICAL issues are found at paragraph boundaries. The translator's job is to **prevent** them by:
1. Monitoring output length
2. Finding a natural stopping point before the limit
3. Completing the thought even if it means a slightly shorter chunk

---

## Summary: The FFXVI Method V2.0

### Original Three Commandments (V1.0 — Proven)

1. **CONTRACTIONS ARE ELEGANT** — Formality comes from vocabulary, not grammar
2. **PERSONALITY OVER PROTOCOL** — Character voice > rigid formality rules
3. **EMOTIONAL DIRECTNESS** — Express feelings directly, no safety wrappers

### New Six Commandments (V2.0 — Hardened)

4. **NAMES ARE IMMUTABLE** — Once the manifest locks a name, it never changes
5. **POV IS SACRED** — Third-person volumes stay third-person, even in dreams
6. **CULTURAL COLOR ENRICHES** — Preserve chai/vino/mead, don't flatten to "tea/wine/drink"
7. **BATTLES MUST BE CLEAR** — Physical choreography > purple prose
8. **CONTINUITY IS CUMULATIVE** — Each chapter inherits from all before it
9. **COMPLETE EVERY SENTENCE** — Never truncate, especially at chunk boundaries

---

### Quick Reference: Victorian vs FFXVI

| Victorian Translation | FFXVI-Style Translation |
|----------------------|------------------------|
| "I do not believe that to be wise." | "I don't think that's wise." |
| "Can you not see I am occupied?" | "Can't you see I'm busy?" |
| "I shall take my leave." | "I'll take my leave." |
| "If you will excuse me." | "Excuse me." |
| "I am humbled." | "I'm honored." / "Thank you." |
| "That is quite admirable." | "That's impressive." |
| "The preparations have been completed." | "We're ready." |

---

## Integration with Existing Modules

### Module Priority When `WORLD_SETTING = FANTASY`

1. **THIS MODULE (FANTASY_TRANSLATION_MODULE V2.0)** — Overrides base rules
2. **Module 08 (Anti-Translationese)** — Still applies fully
3. **Module 02 (Boldness)** — Still applies, with fantasy vocabulary
4. **Module 05 (Register)** — OVERRIDDEN by fantasy register rules
5. **Module 03 (Rhythm)** — Still applies (Legato/Staccato/Tenuto)

### Key Overrides

- **Register Module:** Contractions at ALL EPS levels; formality via vocabulary
- **Archetype System:** Use LOYAL_SERVANT, TSUNDERE_PRINCESS, WAR_MAIDEN, FRONTIER_NOBLE
- **Honorifics:** Japanese → English titles (never "-sama" in Western fantasy)
- **Name Enforcement:** Glossary lock auto-corrects variants post-translation
- **POV Enforcement:** Validator flags first-person leaks in third-person volumes

---

## ACTIVATION TRIGGER

This module activates when:
```
WORLD_SETTING = FANTASY
GENRE = WESTERN_FANTASY | ISEKAI | NOBLE_ACADEMY | SWORD_AND_SORCERY
```

When active, it OVERRIDES modern-Japan-specific rules from the base translation engine.

---

*V2.0 hardened by 25d9 audit: Lord Marksman and Vanadis Vol 1 — 89.0/100, Grade A-*
