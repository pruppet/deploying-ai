# Orchestrate chat history, input guardrails, external lookups, and tool calls.
import string
import json
import chromadb
from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from dotenv import load_dotenv
import requests
from utils.logger import get_logger
from assignment_chat.prompts import return_instructions_root
from assignment_chat.prompts import return_blocked_keywords
from assignment_chat.prompts import return_classifier_prompt
from assignment_chat.prompts import return_refusal_messages
from assignment_chat.creature_formatting import format_creature
import os
import random
import re
from assignment_chat.build_index import CHROMA_DIR, COLLECTION_NAME, get_embedding_function
from assignment_chat.dice_encounter import calculate_encounter, roll_dice




_logs = get_logger(__name__)

load_dotenv(".env")
load_dotenv(".secrets")


if not os.environ.get("API_GATEWAY_KEY"):
    raise ValueError("Missing API_GATEWAY_KEY environment variable")

llm = init_chat_model(
    "gpt-4o-mini",
    model_provider="openai",
    base_url="https://k7uffyg03f.execute-api.us-east-1.amazonaws.com/prod/openai/v1",
    api_key="gateway-auth-is-in-x-api-key",
    default_headers={"x-api-key": os.environ["API_GATEWAY_KEY"]},
)

def refusal() -> str:
    return random.choice(return_refusal_messages())

def is_blocked_by_classifier(message: str) -> bool:
    result = llm.invoke([
        SystemMessage(content=return_classifier_prompt()),
        HumanMessage(content=message),
    ])
    classification = result.content.strip().upper()
    if classification not in {"ALLOW", "BLOCK"}:
        raise ValueError(f"Unexpected classifier response: {result.content!r}")
    return classification == "BLOCK"

@tool
def get_dnd_info(type: str, name: str) -> str:
    """
    Retrieve a D&D creature's information from the Open5e API.
    The supported type is "creature", "creatures", or "species"; 
    Name is the complete creature name exactly as the user gave it,
    including all qualifiers such as age, size or colour (e.g. 
    'Adult Black Dragon', not 'Black Dragon').
    """

    response = get_dnd_info_from_service(type, name)

    return get_dnd_info_from_response(name, response)


@tool
def search_campaign_lore(query: str) -> str:
    """Search the indexed campaign notes for relevant characters, places, events, 
    and lore. If a question concerns several named entities, call this tool once 
    for each entity with a focused query (e.g. "Saltwall Garrison leader"), rather 
    than one combined query."""
    if not query.strip():
        raise ValueError("Campaign lore search query cannot be empty")

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
    )
    results = collection.query(
        query_texts=[query.strip()],
        n_results=4,
        include=["documents", "metadatas"],
    )

    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    if not documents:
        return "No relevant campaign notes were found."

    matches = []
    for index, document in enumerate(documents):
        if not document:
            continue
        metadata = metadatas[index] if index < len(metadatas) else {}
        visibility = "[DM ONLY] " if metadata.get("dm_only") else ""
        source = metadata.get("source_file", "unknown source")
        section = metadata.get("section", "Campaign note")
        matches.append(f"{visibility}{section} ({source}):\n{document}")

    return "\n\n".join(matches) or "No relevant campaign notes were found."


tools = [get_dnd_info, search_campaign_lore, roll_dice, calculate_encounter]
tools_by_name = {registered_tool.name: registered_tool for registered_tool in tools}
llm_with_tools = llm.bind_tools(tools)


def get_dnd_info_from_service(type: str, name: str):
    if type.casefold() not in {"creature", "creatures", "species"}:
        raise ValueError(f"Unsupported D&D information type: {type!r}")
    elif type.casefold() in {"creature", "creatures"}:
        type = "creatures"
    else:
        type = "species"

    url = f"https://api.open5e.com/v2/{type}"
    response = requests.get(
        url,
        params={"name": string.capwords(name), "format": "json"},
        timeout=15,
    )
    response.raise_for_status()
    _logs.info(response.request.url)
    return response

def get_dnd_info_from_response(name: str, response: requests.Response) -> str:
    results = response.json().get("results", [])
    monster = next(
        (result for result in results
         if result.get("name", "").casefold() == name.casefold()),
        None,
    )
    if monster is None:
        formatted_response = f"No Open5e monster found with the name {name!r}"
    else:
        formatted_response = format_creature(monster)
    _logs.info(f"Retrieved D&D info for {name}: {formatted_response}")
    return formatted_response


def extract_text_content(content) -> str:
    """
    Gradio's Chatbot normalizes string content into a list of parts like
    [{"type": "text", "text": "..."}], which the Responses API does not accept
    as-is. Flatten back down to plain text.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return "" if content is None else str(content)


def sanitize_history(history: list[dict]) -> list[HumanMessage | AIMessage]:
    clean_history: list[HumanMessage | AIMessage] = []
    for msg in history:
        role = msg.get("role")
        content = extract_text_content(msg.get("content"))
        if role == "user":
            clean_history.append(HumanMessage(content=content))
        elif role == "assistant":
            clean_history.append(AIMessage(content=content))
        else:
            raise ValueError(f"Unsupported chat history role: {role!r}")
    return clean_history


def dnd_chat(message: str, history: list[dict] | None = None) -> str:
    _logs.info(f'User message: {message}')
    instructions = return_instructions_root()

    if any(re.search(pattern, message, flags=re.IGNORECASE)
           for pattern in return_blocked_keywords()):
        return refusal()
    
    if is_blocked_by_classifier(message):
        return refusal()
    
    langchain_messages = [SystemMessage(content=instructions)]
    langchain_messages.extend(sanitize_history(history or []))
    langchain_messages.append(HumanMessage(content=message))

    response = llm_with_tools.invoke(langchain_messages)
    for _ in range(5):
        if not response.tool_calls:
            return extract_text_content(response.content)

        langchain_messages.append(response)
        for tool_call in response.tool_calls:
            selected_tool = tools_by_name.get(tool_call["name"])
            if selected_tool is None:
                raise ValueError(f"Model requested unknown tool: {tool_call['name']}")

            _logs.info(f'Tool call: {tool_call["name"]} with args {tool_call["args"]}')
            try:
                result = selected_tool.invoke(tool_call["args"])
            except ValueError as exc:
                # Let the model explain or correct user-facing tool input errors.
                result = {"error": str(exc)}
            result_content = (
                json.dumps(result, ensure_ascii=False)
                if isinstance(result, (dict, list))
                else str(result)
            )
            langchain_messages.append(
                ToolMessage(content=result_content, tool_call_id=tool_call["id"])
            )

        response = llm_with_tools.invoke(langchain_messages)

    if response.tool_calls:
        raise RuntimeError("Tool call limit reached before the assistant returned a final answer")
    return extract_text_content(response.content)
