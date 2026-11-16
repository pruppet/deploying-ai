# The Chronicler's Archive: A D&D Campaign Assistant

The Chronicler's Archive is a Gradio chat assistant for Dungeon Masters. It can look up creature and species entries from Open5e, search a local index of campaign notes, roll dice, and estimate encounter difficulty from XP budgets.

The sample campaign is an original adaptation inspired by the *Salvage Operation* chapter of *Ghosts of Saltmarsh*, set in and around the fishing town of Saltmarsh.

## Contents

1. [Persona](#persona)
2. [Services](#services)
3. [User Interface and Memory](#user-interface-and-memory)
4. [Guardrails and Disclosure Limits](#guardrails-and-disclosure-limits)
5. [Implementation Decisions](#implementation-decisions)
6. [Running the App](#running-the-app)
7. [File Structure](#file-structure)
8. [Limitations and Future Work](#limitations-and-future-work)
9. [Sources and Attribution](#sources-and-attribution)

## Persona

The assistant speaks as a measured, in-world chronicler or archivist while keeping answers clear. The system prompt asks it to get to the point, use retrieval tools when relevant, and avoid answering unrelated topics.
For campaign questions, answers should be grounded in the relevant notes; the exact response depends on what the search retrieves.

## Services

### Open5e lookups

`get_dnd_info` calls the Open5e API V2 creature or species endpoint:

- `https://api.open5e.com/v2/creatures`
- `https://api.open5e.com/v2/species`

The request sends a title-cased name and `format=json`. The app then selects a result whose name exactly matches the requested name, ignoring letter case. It does not currently filter results by source document or search for partial name matches, so it cannot guarantee that a result is from a particular D&D rules release. If there is no exact match, it reports that no entry was found; it does not offer a list of near matches.

Creature data is formatted as a Markdown stat block by `creature_formatting.py`. The formatter labels proficiency bonus as derived when it calculates a missing value from challenge rating. The species endpoint is also available through this tool. For quick NPCs or creatures, the system prompt guides the model to combine a selected creature stat block with a newly invented name and short backstory; it uses `roll_dice` to choose a species from a fixed list when the user has not specified one. This is model-guided behavior, not a separate deterministic generator.

If there is no exact match, the tool only reports that no entry was found. Although the prompt asks the model to suggest close names, the current lookup does not return partial matches to support that suggestion.

### Campaign-lore search

`search_campaign_lore` uses ChromaDB to retrieve campaign-note sections relevant to a query. The Markdown notes are grouped by entity type under `campaign_notes/`. A note may have a YAML-like header followed by `##` sections.

`build_index.py` splits notes into non-empty `##` sections. Each document is prefixed with its entity name, type, and section heading; header fields are stored as metadata. A section whose heading contains `DM Only` receives the metadata flag `dm_only: true`.

The embedding function uses `text-embedding-3-small` through the course gateway, authenticated with `API_GATEWAY_KEY`. The persistent ChromaDB collection is named `campaign_lore` and is stored in `chroma_db/` with cosine distance. Rebuilding the index deletes and recreates the collection, so edits and deletions in the notes are reflected.

At the time this README was updated, the notes contained 19 Markdown files, the collection contained 123 chunks, and `chroma_db/` occupied approximately 2.7 MB. The query tool asks ChromaDB for up to four relevant sections per search. For questions spanning multiple named entities, its tool description asks the model to make a focused search for each entity; the model controls whether it follows that guidance.

### Dice and encounter tools

`dice_encounter.py` provides two local LangChain tools:

- **`roll_dice`** accepts standard notation such as `2d6+3`, `4d6dl1`, `2d20kh1`, and phrases such as `4d6 drop lowest` or `d20 with advantage`. It parses expressions without evaluating them as Python code, limits rolls to 100 dice with at most 1,000 sides each, and returns individual rolls and the total.
- **`calculate_encounter`** sums monster XP and compares it with party XP budgets labeled Low, Moderate, and High. It accepts one level per party member and, for each monster, either an XP value or a challenge rating. Challenge ratings are converted to XP using a local lookup table. The tool also returns cautionary notes for encounters exceeding the High budget, large groups of monsters, or a challenge rating above the party's highest level.

The XP-budget and challenge-rating tables are constants in the code and have not been independently checked against the 2024 *Dungeon Master's Guide*.

## User Interface and Memory

The interface is a Gradio `ChatInterface` with a custom dark, fantasy-inspired theme. Its CSS imports the IM Fell English SC and Alegreya fonts from Google Fonts.

The current app passes the conversation history Gradio provides into the model on each turn. It does not summarize or truncate long conversations. The app does not set a fixed server port in `launch()`; use the local URL printed by Gradio when it starts.

## Guardrails and Disclosure Limits

### Input checks

Before the chat model is called, the latest user message is checked in two ways:

1. A case-insensitive regular-expression filter checks for configured restricted topics and phrases, including references to cats or dogs, astrology, Taylor Swift, and some prompt-injection wording.
2. The same `gpt-4o-mini` model is called as a classifier and asked to return exactly `ALLOW` or `BLOCK`.

Messages classified as blocked receive a randomly selected in-world refusal. Only the latest message is checked by these filters; prior conversation history is not separately classified. Unexpected classifier text or a classifier request failure raises an error rather than producing a refusal. These checks are input guardrails, not a security boundary, and there is no output scan that can guarantee the model will not reveal sensitive text.

### DM-only campaign material

Retrieved sections marked `DM ONLY` are labeled in the tool result, and the system prompt instructs the model not to disclose them unless the user is acting as the Dungeon Master. The app does not authenticate the user's role and does not filter those sections out before sending them to the model. Do not treat this prompt instruction as access control.

## Implementation Decisions

- **Open5e API V2:** The app uses the current V2 creature and species endpoints. It sends a name and formats the result locally. It currently does not use Open5e's source-document filter, so API results should not be described as restricted to the 2024 SRD.
- **Campaign notes as the lore source:** Local Markdown keeps campaign facts editable and separate from model-generated answers. Retrieved notes are intended to ground campaign-specific responses.
- **One chunk per section with an entity prefix:** A section can be retrieved on its own while retaining its entity, type, and heading context. Entity fields are stored as metadata for potential filtering or display.
- **Focused searches for multiple entities:** Searching separately can give each named entity a chance to appear among the top results, rather than spending the retrieval limit on one broad query.
- **Model and embedding configuration:** The chat model and classifier both use `gpt-4o-mini`. Lore indexing and querying use `text-embedding-3-small`. These are configured through the course gateway; the API key is supplied through `API_GATEWAY_KEY`, not stored in source code.
- **Tool errors:** `ValueError` from a tool is returned to the model as an error result so it can explain or correct invalid input. Other exceptions propagate and can fail the request.

## Running the App

1. Install the project dependencies and activate the repository's Python environment as described in the repository's `SETUP.md`.
2. Ensure `API_GATEWAY_KEY` is available in the process environment. The app calls `load_dotenv(".env")` and `load_dotenv(".secrets")` relative to the current working directory, so when following the commands below, a private `05_src/.secrets` file can hold that variable. Do not commit the key.
3. From the repository root, run:

   ```bash
   cd 05_src
   python -m assignment_chat.app
   ```

4. Open the local URL printed by Gradio.

To rebuild the campaign index after editing notes, run from `05_src`:

```bash
python -m assignment_chat.build_index
```

The index is persisted locally in `assignment_chat/chroma_db/`. Rebuilding replaces the existing `campaign_lore` collection.

## File Structure

```text
05_src/assignment_chat/
    app.py                  Gradio interface, theme, and launch
    main.py                 Chat orchestration, guardrails, and tool routing
    prompts.py              Assistant instructions and restricted-topic policy
    creature_formatting.py  Open5e stat-block formatting
    dice_encounter.py       Dice roller and encounter calculator
    build_index.py          Campaign-note parsing and ChromaDB index builder
    campaign_notes/         Campaign lore in Markdown, grouped by entity type
    chroma_db/              Persisted ChromaDB collection
    readme.md               This guide
```

## Limitations and Future Work

- The Open5e lookup does not restrict results to a particular source document, does not search for partial matches, and does not suggest near matches when there is no exact name match.
- Campaign retrieval is semantic top-four search, not a guarantee that every relevant note will be found. DM-only filtering is prompt-based and is not an authenticated player/DM access-control feature.
- The encounter XP tables are local constants that need verification against the intended rules reference. The calculator compares total XP to summed party budgets and does not implement every encounter-balancing rule.
- The tool asks the model to obtain creature XP where possible, but the model may need user-provided XP or challenge rating for content unavailable through the API. Tool correctness still depends on the arguments it chooses.
- Full conversation history is sent each turn; there is no summarization or token-budget management.
- Guardrails classify only the latest user message and do not provide robust prompt-injection protection or output filtering.
- Add automated tests for API response variations, classifier failures, multi-entity retrieval, and the DM-only disclosure policy.
- Consider adding a player-safe mode that filters DM-only sections before they are included in model context.

## Sources and Attribution

- Creature and species records are retrieved from the [Open5e API](https://open5e.com/api-docs). See the [Open5e legal information](https://open5e.com/legal) and the license associated with each source document before redistributing API-derived content. The current code does not request or display each record's source document, so it does not establish a single license or SRD attribution for all returned records.
- The sample campaign is an original adaptation inspired by *Ghosts of Saltmarsh* (Wizards of the Coast, 2019). The campaign notes are original writing and are intended not to reproduce text from the published adventure.
