"""Intent classification and routing for interactive requests.

Distinguishes greetings, acknowledgements, help inquiries, ambiguous queries,
informational questions, and genuine coding tasks without fragile verb whitelists.
"""

from dataclasses import dataclass
import re
from typing import Optional, Set


@dataclass(frozen=True)
class IntentResult:
    kind: str  # "greeting", "acknowledgement", "help", "ambiguous", "question", "coding"
    reason: str
    response: Optional[str] = None
    clarification: Optional[str] = None


GREETING_WORDS: Set[str] = {
    "hi", "hello", "hey", "howdy", "greetings", "yo", "sup", "hola",
    "heya", "hiya", "welcome",
}

GREETING_PHRASES: Set[str] = {
    "good morning", "good afternoon", "good evening", "good day",
}

CONVERSATIONAL_QUESTION_PHRASES: Set[str] = {
    "how are you", "how are you doing", "hows it going", "how is it going",
    "how are things", "are you doing fine", "are you fine", "are you ok",
    "are you okay", "how do you do", "what's new", "whats new",
    "what's up", "whats up", "who are you", "what are you", "what happened",
    "what happened?", "are you there", "are you working", "is this working",
}

ADDRESS_WORDS: Set[str] = {
    "miser", "agent", "assistant", "there", "bot", "friend", "team", "all",
}

ACK_WORDS: Set[str] = {
    "thanks", "thank you", "thx", "ty", "ok", "okay", "k", "got it",
    "understood", "cool", "great", "perfect", "sounds good", "nice",
    "alright", "all right", "sure", "roger", "acknowledged", "done",
    "bye", "goodbye", "cheers", "awesome", "sweet", "neat", "splendid",
    "wonderful",
}

ACK_PHRASES: Set[str] = {
    "thank you very much", "thanks a lot", "many thanks", "sounds good",
    "looks good", "all right", "no problem", "this great", "this is great",
    "that is great", "thats great", "that's great", "looks great",
    "sounds great", "good job", "nice work", "well done", "keep it up",
}

HELP_PHRASES: Set[str] = {
    "help", "help me", "what can you do", "what can you do?",
    "what are your capabilities", "how do i use this", "how does this work",
    "how to use", "commands", "show commands", "list commands", "usage",
    "options", "what do you do",
}

AMBIGUOUS_VAGUE_TERMS: Set[str] = {
    "maybe", "hmm", "hmmm", "not sure", "idk", "something", "dunno",
    "what", "why", "code", "file", "files", "test", "tests", "bug",
    "pricing", "pricing.py", "discount", "repo",
}

QUESTION_STARTERS = (
    "what", "where", "when", "why", "who", "which", "how", "whose",
    "is", "are", "do", "does", "did", "can", "could", "would", "will", "should", "have", "has",
)

EXPLAIN_PHRASES = (
    "explain", "describe", "tell me about", "walk me through",
    "show me", "can you explain", "could you explain", "what does",
    "how does", "what is", "where is", "why is", "why does", "why do",
    "how do i", "how can i", "what should i", "how to",
)

CODING_ACTIONS: Set[str] = {
    "fix", "repair", "solve", "patch", "modify", "change", "update",
    "edit", "refactor", "implement", "add", "remove", "delete", "rewrite",
    "replace", "correct", "create", "write", "make", "ensure", "prevent",
    "support", "adjust", "convert", "simplify", "clean", "extract",
    "inline", "rename", "revert", "inspect", "examine", "explore",
    "review", "scan", "check",
}

CODING_TARGETS: Set[str] = {
    "bug", "issue", "error", "exception", "failure", "fail", "failing",
    "test", "tests", "formula", "calculation", "discount", "price", "pricing",
    "function", "method", "class", "module", "file", "code", "logic",
    "algorithm", "typo", "import", "return", "argument", "parameter",
    "variable", "validation", "docstring", "comment", "api", "syntax",
}

DECLARATIVE_CODING_PATTERNS = [
    re.compile(r"\b(should|must|needs? to|ought to)\s+(be|return|subtract|add|handle|raise|calculate|check|equal|match)\b", re.I),
    re.compile(r"\b(is|are)\s+(wrong|incorrect|broken|failing|buggy|missing|not subtracted|not added)\b", re.I),
    re.compile(r"\bmake\s+(the\s+)?tests?\s+pass\b", re.I),
    re.compile(r"\b(fix|repair|solve|patch)\s+.*", re.I),
    re.compile(r"\b(preserve|maintain)\s+(the\s+)?(existing\s+)?(tests|public api)\b", re.I),
    re.compile(r"[=+\-*/%><]\s*\(?[\w\s+\-*/%]+\)?", re.I),
]


def classify_intent(text: str) -> IntentResult:
    """Classify user input into greeting, acknowledgement, help, ambiguous, question, or coding."""
    raw = text.strip()
    if not raw:
        return IntentResult(
            kind="ambiguous",
            reason="Empty input",
            clarification="Please enter a coding task or question. Type /help for available commands."
        )

    if raw.startswith("/"):
        return IntentResult(kind="command", reason="Slash command")

    text_lower = raw.lower()
    cleaned = re.sub(r"[^\w\s]", " ", text_lower).strip()
    words = cleaned.split()

    # 1. Check for genuine coding intent first if input contains explicit code repair patterns
    # or coding action + coding target, to ensure natural phrases like "hi, please fix discount"
    # or "can you update pricing.py" are recognized as coding tasks.
    has_declarative_coding = any(p.search(raw) for p in DECLARATIVE_CODING_PATTERNS)
    has_coding_action = any(w in CODING_ACTIONS for w in words)
    has_coding_target = any(w in CODING_TARGETS for w in words) or any("." in token for token in raw.split())

    # Check if this is an inquiry question rather than a coding delegation
    # e.g. "Is the formula correct?" vs "Please correct the formula"
    is_inquiry_question = cleaned.startswith(("is the ", "is this ", "are the ", "are these ", "does the ", "do the ")) and "?" in raw

    # Check if this is an advice question rather than a coding delegation
    # e.g. "How do I fix the discount?" vs "Can you fix the discount?"
    is_advice_question = (
        cleaned.startswith("how do i")
        or cleaned.startswith("how can i")
        or cleaned.startswith("how to")
        or cleaned.startswith("what should i")
        or cleaned.startswith("where should i")
    )

    # Question check: starts with an explanation/question phrase and does NOT delegate a coding fix
    is_explaining = any(cleaned.startswith(p) for p in EXPLAIN_PHRASES)

    if (has_declarative_coding or (has_coding_action and (has_coding_target or len(words) <= 3))) and not is_advice_question and not is_explaining and not is_inquiry_question:
        return IntentResult(kind="coding", reason="Coding task requested")

    # 2. Conversational question check (must be answered by the live model via Bifrost, NOT canned text)
    is_conversational_question = (
        cleaned in CONVERSATIONAL_QUESTION_PHRASES
        or any(cleaned.startswith(p) for p in (
            "how are you", "how are you doing", "hows it going", "how is it going",
            "how are things", "are you doing", "are you fine", "are you ok",
            "are you okay", "what is up", "whats up", "what's up", "who are you",
            "what are you", "what happened", "what did you",
        ))
    )
    if is_conversational_question:
        return IntentResult(kind="question", reason="Conversational question for the model")

    # 3. Greeting check: pure salutations without questions or task instructions
    if cleaned in GREETING_WORDS or cleaned in GREETING_PHRASES:
        return IntentResult(
            kind="greeting",
            reason="Pure greeting",
            response=(
                "Hello! I'm MISER, your focused coding assistant. How can I help you today? "
                "You can describe a coding task, ask questions about the repository, or type /help for commands."
            ),
        )
    if words and words[0] in GREETING_WORDS:
        remainder = words[1:]
        if all(w in ADDRESS_WORDS or w in GREETING_WORDS for w in remainder):
            return IntentResult(
                kind="greeting",
                reason="Greeting with address",
                response=(
                    "Hello! I'm MISER, your focused coding assistant. How can I help you today? "
                    "You can describe a coding task, ask questions about the repository, or type /help for commands."
                ),
            )

    # 4. Acknowledgement check
    if cleaned in ACK_WORDS or cleaned in ACK_PHRASES:
        return IntentResult(
            kind="acknowledgement",
            reason="Pure acknowledgement",
            response="You're welcome! Let me know what you'd like to work on next.",
        )
    if words and all(w in ACK_WORDS or w in ADDRESS_WORDS for w in words):
        return IntentResult(
            kind="acknowledgement",
            reason="Acknowledgement sequence",
            response="You're welcome! Let me know what you'd like to work on next.",
        )

    # 5. Help inquiry check
    if cleaned in HELP_PHRASES or (words and words[0] == "help" and len(words) <= 3):
        return IntentResult(
            kind="help",
            reason="Help requested",
            response=(
                "MISER is a focused coding agent designed for efficient model usage, "
                "controlled edits, and verified changes.\n\n"
                "You can:\n"
                "  - Request code changes: e.g. 'Fix the percentage discount calculation'\n"
                "  - Ask questions about code: e.g. 'What does discounted_price do?'\n"
                "  - Use terminal commands:\n"
                "      /help     Show available commands\n"
                "      /status   Show workspace, model, and budget\n"
                "      /model    Select a Bifrost model\n"
                "      /test     Set acceptance command\n"
                "      /budget   Set task token budget\n"
                "      /map      Inspect task-ranked repo symbols\n"
                "      /diff     Show last task's patch\n"
                "      /receipt  Show token receipt\n"
                "      /exit     Leave MISER"
            ),
        )

    # 6. Ambiguous check: very short inputs or vague terms lacking action or context
    raw_tokens = raw.split()
    if len(raw_tokens) == 1:
        token = raw_tokens[0].lower()
        if token not in CODING_ACTIONS:
            return IntentResult(
                kind="ambiguous",
                reason=f"Single word query '{raw}' is ambiguous",
                clarification=(
                    f"Your request '{raw}' is ambiguous. Did you want to inspect it, "
                    "make a code change, run tests, or ask a question? Please clarify."
                ),
            )
    if cleaned in AMBIGUOUS_VAGUE_TERMS or (len(words) <= 2 and all(w in AMBIGUOUS_VAGUE_TERMS for w in words)):
        return IntentResult(
            kind="ambiguous",
            reason="Vague expression",
            clarification=(
                "Your request is ambiguous. Did you want to inspect files, make a code change, "
                "run tests, or ask a question? Please clarify what you'd like to do."
            ),
        )

    # 7. Informational and conversational questions
    if is_advice_question or is_explaining or "?" in raw or (words and words[0] in QUESTION_STARTERS):
        return IntentResult(
            kind="question",
            reason="Informational or conversational question",
        )

    # If the user provided action words or target words related to code/tests/files, treat as coding task
    if has_coding_action or has_coding_target or has_declarative_coding:
        return IntentResult(kind="coding", reason="General task description")

    # Otherwise, general conversational remark to be answered by the model
    return IntentResult(kind="question", reason="Conversational remark for the model")
