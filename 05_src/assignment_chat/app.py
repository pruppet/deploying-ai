# Gradio entry point for the campaign assistant's themed chat interface.
import gradio as gr
from assignment_chat.main import dnd_chat
from dotenv import load_dotenv
from typing import Optional
import os

from utils.logger import get_logger

_logs = get_logger(__name__)

load_dotenv('.secrets')


CSS = """
@import url('https://fonts.googleapis.com/css2?family=IM+Fell+English+SC&family=Alegreya:ital,wght@0,400;0,600;1,400&display=swap');

.gradio-container {
    max-width: 880px !important;
    margin: 0 auto !important;
}

/* Title block */
#archive-title {
    text-align: center;
    padding: 1.5rem 0 0.5rem;
}
#archive-title h1 {
    font-family: 'IM Fell English SC', Georgia, serif;
    font-weight: 400;
    font-size: 2.6rem;
    letter-spacing: 0.02em;
    color: #E6DCC5;
    margin: 0 0 0.35rem;
}
#archive-title p {
    font-style: italic;
    color: #A9A08C;
    margin: 0;
}
#archive-title::after {
    content: "";
    display: block;
    width: 120px;
    height: 1px;
    margin: 1rem auto 0;
    background: #B8964A;
}

/* Assistant replies: vellum leaves with a gilt edge */
.message.bot {
    background: #E8DDC4 !important;
    color: #2B241B !important;
    border: none !important;
    border-left: 3px solid #B8964A !important;
    border-radius: 2px !important;
    line-height: 1.65;
}
.message.bot p,
.message.bot li,
.message.bot strong,
.message.bot em {
    color: #2B241B !important;
}

/* User messages: quiet slate */
.message.user {
    background: #2C3244 !important;
    color: #E6DCC5 !important;
    border: 1px solid #3A4052 !important;
    border-radius: 10px !important;
    line-height: 1.6;
}

/* Visible keyboard focus */
textarea:focus-visible,
button:focus-visible {
    outline: 2px solid #5E9C8A !important;
    outline-offset: 2px;
}

@media (max-width: 600px) {
    #archive-title h1 { font-size: 2rem; }
}
"""

THEME = gr.themes.Base(
    font=[
        gr.themes.GoogleFont("Alegreya"),
        gr.themes.Font("Georgia"),
        gr.themes.Font("serif"),
    ],
).set(
    body_background_fill="#161A23",
    body_background_fill_dark="#161A23",
    body_text_color="#E6DCC5",
    body_text_color_dark="#E6DCC5",
    block_background_fill="#222736",
    block_background_fill_dark="#222736",
    block_border_color="#3A4052",
    block_border_color_dark="#3A4052",
    input_background_fill="#1C202B",
    input_background_fill_dark="#1C202B",
    input_border_color="#3A4052",
    input_border_color_dark="#3A4052",
    button_primary_background_fill="#5E9C8A",
    button_primary_background_fill_dark="#5E9C8A",
    button_primary_background_fill_hover="#6FAE9B",
    button_primary_background_fill_hover_dark="#6FAE9B",
    button_primary_text_color="#10140F",
    button_primary_text_color_dark="#10140F",
)


with gr.Blocks(title="The Chronicler's Archive") as chat:
    gr.Markdown(
        "# The Chronicler's Archive\n"
        "Monsters, spells, conditions, campaign lore and dice, kept for the Dungeon Master.",
        elem_id="archive-title",
    )
    gr.ChatInterface(
        fn=dnd_chat,
        chatbot=gr.Chatbot(height=560, show_label=False),
        textbox=gr.Textbox(
            placeholder="Ask about a monster, spell, NPC or roll",
            show_label=False,
        ),
        examples=[
            "What are the stats for an aboleth?",
            "Roll 4d6 and drop the lowest",
            "Who runs the the three factions?",
        ],
    )

if __name__ == "__main__":
    _logs.info('Starting DND Chat App...')
    chat.launch(
        theme=THEME, 
        css=CSS,)
