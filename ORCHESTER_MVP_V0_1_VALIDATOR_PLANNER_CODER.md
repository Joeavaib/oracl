# Backend‑First v0.1 — Orchester‑MVP: **Validator → Planner → Validator → Coder**

**Ziel (dein Wunsch, klar priorisiert):**  
1) Modelle **spezialisieren** (Prompt/Tools + LoRA/QLoRA, kein Full‑FT)  
2) Modelle **sequentiell** orchestrieren, mit **Validator** an jedem Zwischenstep (Routing + Kompression)  
3) IDE/Frontend: **später / optional** (Backend muss zuerst stabil)

Dieses Dokument hält die **Start‑Pipeline** fest:

> **Validator (V)** → **Planner (P)** → **Validator (V)** → **Coder (C)**

---

## 0. Begriffe und Prinzipien

### 0.1 Spezialisten
- **Planner**: erzeugt *Plan + Ziel-Dateien + Risiken + Kontextbedarf*
- **Coder**: erzeugt *Patch (Unified Diff) + kurze Begründung + Referenzen auf Plan*

### 0.2 Validator
Der Validator ist dein **Dirigent**:
- validiert **Schema + harte Regeln**
- bewertet (Rubrik/Heuristiken)
- entscheidet **accept / retry / reroute / escalate / abort**
- komprimiert den Kontext für den nächsten Schritt (“handoff brief”)

### 0.3 “Einheitliche Verträge”
Alles, was ein Modell ausgibt, muss **strukturierte JSON‑Ausgaben** liefern (Pydantic‑Schemas).  
Damit werden:
- Retries deterministisch
- Routing sauber
- Training (SFT) automatisch aus den gleichen Artefakten möglich

---

## 1. Architektur (Backend‑First)

```text
Client (CLI / später UI)
    |
    v
FastAPI Gateway  (ein Entry)
    |
    v
LangGraph Orchestrator
    |
    +--> Validator Node (PydanticAI)  ---> decision + handoff_brief
    |
    +--> Planner Node (LLM)           ---> PlannerOutput
    |
    +--> Validator Node (PydanticAI)  ---> decision + handoff_brief
    |
    +--> Coder Node (LLM)             ---> CoderOutput
    |
    v
Result (CoderOutput + Logs/Artifacts)
```

**Optional früh, aber nicht zwingend im MVP:** Context/Index Tool (Retrieve Snippets), das der Validator bei `reroute=retrieve_context` anfordern kann.

---

## 2. Scope v0.1 (Was wir jetzt bauen)

### 2.1 In Scope
- Pipeline: **V→P→V→C**
- Strikte Output‑Schemas: ValidatorDecision, PlannerOutput, CoderOutput
- Standardisierte **Retry‑Mechanik** (schema repair / reduce scope / ask for missing context)
- Persistenz: Run‑Ordner mit Request/Outputs/Decisions
- Minimaler “Tool‑Slot” für Retrieval (auch wenn index engine später stärker wird)

### 2.2 Out of Scope (für später)
- IDE/Continue Integration
- Vollautomatische Distillation (du labelst Validator zunächst manuell)
- Multi‑agent graph branching (mehr als 1 Planner, 1 Coder) – kommt nach MVP

---

## 3. Datenmodelle (Contracts)

> **Wichtig:** Wir halten den Validator‑Request/Labeling‑Ansatz kompatibel zu deiner bestehenden Validator‑Doku (v3): `RequestRecord`, `PartialLabels`, `FinalValidatorLabel` etc.  
> Hier definieren wir zusätzlich den **Runtime PipelineState** für LangGraph.

### 3.1 PipelineState (Runtime)
Minimaler Zustand, der von Node zu Node fließt:

```json
{
  "run_id": "uuid",
  "created_at": "2026-02-06T10:00:00+01:00",

  "task": {
    "task_id": "string",
    "goal": "string",
    "repo_root": "/abs/path/or/repo-id",
    "constraints": ["string"],
    "acceptance_criteria": ["string"]
  },

  "inputs": {
    "user_prompt": "string",
    "files_in_scope": ["path"],
    "context_snippets": [
      {"path":"file.py","start":10,"end":40,"text":"...","score":0.82,"kind":"lexical|embed"}
    ]
  },

  "artifacts": {
    "planner": null,
    "coder": null
  },

  "validator": {
    "history": [
      {
        "stage": "pre_planner|post_planner|...",
        "decision": { "action":"accept|retry|reroute|escalate|abort" }
      }
    ]
  },

  "routing": {
    "next": "planner|coder|end|retrieve_context",
    "retries": {
      "planner": 0,
      "coder": 0
    }
  }
}
```

### 3.2 ValidatorDecision (für jeden Validator‑Step)
**Dieser Output ist der zentrale Contract.**  
Er steuert die Pipeline und bildet später Trainingsdaten für deinen Validator.

```json
{
  "action": "accept|retry|reroute|escalate|abort",
  "confidence": 0.0,
  "reasons": ["string"],

  "retry": {
    "strategy": "force_schema|reduce_scope|ask_missing|tool_verify|rephrase",
    "max_additional_tries": 1,
    "prompt_patch": "string"
  },

  "route": {
    "next_node": "planner|coder|retrieve_context|end",
    "required_context": ["file:path", "symbol:foo", "tests:..."]
  },

  "handoff_brief": {
    "facts": ["string"],
    "constraints": ["string"],
    "open_questions": ["string"],
    "do_next": "string",
    "do_not": ["string"]
  }
}
```

---

## 4. Spezialisten‑Schemas

### 4.1 PlannerOutput
Der Planner soll **nicht** coden. Er strukturiert den Lösungsweg.

```json
{
  "summary": "1-2 Sätze was gelöst wird",
  "plan_steps": [
    {"step": 1, "intent": "string", "files": ["path"], "notes": "string"}
  ],
  "files_to_touch": ["path"],
  "risks": [
    {"risk": "string", "severity": "low|medium|high", "mitigation": "string"}
  ],
  "needs_context": [
    {"kind":"file|symbol|test|log", "query":"string", "why":"string"}
  ],
  "success_signals": [
    {"signal":"string", "how_to_check":"string"}
  ]
}
```

### 4.2 CoderOutput
Der Coder liefert **Patch** + minimal erklärenden Text + Referenz auf Plan.

```json
{
  "patch_unified_diff": "diff --git ...",
  "touched_files": ["path"],
  "rationale": [
    "Kurz warum dieser Patch korrekt ist",
    "Welche Edge‑Cases wurden bedacht"
  ],
  "verification": [
    {"command":"pytest -q", "expected":"all green", "notes":"string"}
  ],
  "followups": [
    {"type":"test|refactor|docs", "why":"string"}
  ]
}
```

---

## 5. Prompt‑Profile (v0.1)

> Diese Prompts sind bewusst kurz & robust. Du kannst sie später feintunen.

### 5.1 Planner — System Prompt (Template)
- Fokus: Plan, Scope, Risiko, benötigter Kontext.
- Output: **nur JSON** gemäß PlannerOutput.

```text
Du bist PLANNER. Du schreibst KEINEN Code.
Ziel: Erzeuge einen präzisen Plan, welche Dateien angepasst werden müssen, warum, und wie der Erfolg geprüft wird.
Wenn Kontext fehlt, liste ihn in needs_context.

Ausgabe: ausschließlich gültiges JSON im Schema PlannerOutput.
Keine Markdown-Blöcke. Keine Erklärtexte außerhalb des JSON.
```

### 5.2 Coder — System Prompt (Template)
- Fokus: Patch, sauberer Diff, minimale rationale.
- Output: **nur JSON** gemäß CoderOutput.

```text
Du bist CODER. Du setzt den Plan um.
Regeln:
- Liefere einen Unified Diff, der direkt anwendbar ist.
- Touch so wenige Dateien wie möglich.
- Keine großen Refactors ohne expliziten Plan-Step.
- Wenn etwas fehlt: liefere einen minimalen Patch und nenne Followups.

Ausgabe: ausschließlich gültiges JSON im Schema CoderOutput.
Keine Markdown-Blöcke. Keine Erklärtexte außerhalb des JSON.
```

### 5.3 Validator — System Prompt (Template)
- Fokus: Schema, harte Regeln, Routing, Kompression.
- Output: **nur JSON** gemäß ValidatorDecision.

```text
Du bist VALIDATOR. Du bewertest den Output des vorherigen Nodes.
Aufgaben:
1) Prüfe: Schema korrekt? harte Regeln erfüllt?
2) Entscheide action: accept/retry/reroute/escalate/abort
3) Erzeuge handoff_brief: komprimiert & exakt, damit der nächste Node effizient arbeiten kann.

Ausgabe: ausschließlich gültiges JSON im Schema ValidatorDecision.
Keine Markdown-Blöcke. Keine Erklärtexte außerhalb des JSON.
```

---

## 6. Ablauf‑Logik: V → P → V → C

### 6.1 Stage: Validator (pre_planner)
Input:
- user_prompt + ggf. initiale context_snippets
Validator prüft:
- ist das Ziel eindeutig?
- fehlen kritische Inputs? (z.B. repo_root, files_in_scope, failing logs)
Decision:
- `reroute -> retrieve_context` wenn Kontext klar fehlt
- sonst `accept -> planner`

### 6.2 Stage: Planner
Input:
- user_prompt + validator.handoff_brief + context_snippets
Planner erzeugt PlannerOutput.

### 6.3 Stage: Validator (post_planner)
Validator prüft:
- Plan ist umsetzbar? Scope okay? nicht zu breit?
- files_to_touch plausibel?
- success_signals vorhanden?
Decision:
- `retry` (reduce_scope / ask_missing)
- oder `accept -> coder`

### 6.4 Stage: Coder
Input:
- PlannerOutput + validator.handoff_brief + context_snippets
Coder erzeugt CoderOutput.

> v0.1 endet hier. (Optional später: final validator + automatic tool verify)

---

## 7. Retry‑Policy (v0.1)
- max retries: `planner=2`, `coder=2`
- Validator steuert `prompt_patch` als “Delta” (kein kompletter Prompt‑Rewrite)

**Typische Strategien**
- `force_schema`: “Gib gültiges JSON aus, keine Extras”
- `reduce_scope`: “Bearbeite nur Datei X, lasse Y”
- `ask_missing`: “Welche Information fehlt?”
- `tool_verify`: “Hole Kontext / führe check aus” (später automatisierbar)

---

## 8. Persistenz & Artefakte (damit Training später leicht wird)

Pro Run:
```
runs/<run_id>/
  input.json
  state_initial.json
  validator_pre_planner.json
  planner_output.json
  validator_post_planner.json
  coder_output.json
  state_final.json
  events.jsonl
```

**events.jsonl** enthält jede Node‑Invocation mit timestamps, model_id, tokens, etc.  
Das ist Gold für späteres Debugging und Datengenerierung.

---

## 9. Training‑Ableitung (SFT/LoRA)

### 9.1 Spezialisten‑SFT
Du erzeugst Trainingsbeispiele aus echten Runs:
- Input = handoff_brief + context_snippets + task
- Output = PlannerOutput / CoderOutput JSON

### 9.2 Validator‑SFT (deine “manuelle Distillation”)
- Teachers erzeugen PartialLabels → Merge → FinalValidatorLabel
- Daraus entsteht `distill_train.jsonl` (messages) für den Validator‑Student

---

## 10. Implementations‑Roadmap (kurz, praktisch)

1) **Schemas** als Pydantic Modelle (ValidatorDecision, PlannerOutput, CoderOutput, PipelineState)
2) **LangGraph**: StateGraph mit 4 Nodes (validator_pre, planner, validator_post, coder)
3) **LLM Adapter**: ein einheitlicher `call_llm(model, messages) -> text`
4) **PydanticAI** für Validator (und optional auch für Spezialisten, um JSON‑Parsing zu erzwingen)
5) **Run Storage** + events.jsonl
6) Optional: Retrieval‑Tool Stub, damit `reroute=retrieve_context` schon “lebt”

---

## 11. Definition of Done (v0.1)

- End‑to‑End: ein Run produziert valide JSON‑Outputs für alle Nodes
- Validator kann mindestens:
  - schema errors reparieren (force_schema)
  - scope reduzieren (reduce_scope)
  - rerouten zu retrieve_context (Stub ok)
- Artefakte werden pro Run persistiert (replayable)

---

## 12. Notizen / bewusste Entscheidungen

- Wir lassen IDE‑Integration weg, bis Orchestrierung + Indexing stabil sind.
- Spezialisierung: **LoRA/QLoRA** als Standard (Adapter‑Artefakte).
- Distillation: Validator‑Labels manuell/halbautomatisch, Training via SFT‑Mechanik.

---
