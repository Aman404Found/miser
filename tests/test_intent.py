import unittest
from miser.intent import classify_intent


class IntentClassificationTests(unittest.TestCase):
    def test_greetings(self):
        greetings = [
            "hi", "hello", "hey", "hey there", "good morning", "good afternoon",
            "good evening", "hi miser", "yo", "hello!", "Howdy", "hiya there",
        ]
        for g in greetings:
            with self.subTest(greeting=g):
                res = classify_intent(g)
                self.assertEqual(res.kind, "greeting", f"Failed for {g}: got {res.kind}")
                self.assertIsNotNone(res.response)

    def test_acknowledgements(self):
        acks = [
            "thanks", "thank you", "thx", "ok", "okay", "got it", "understood",
            "sounds good", "cool", "perfect", "great", "all right", "this great",
            "this is great", "looks great", "sounds great"
        ]
        for a in acks:
            with self.subTest(ack=a):
                res = classify_intent(a)
                self.assertEqual(res.kind, "acknowledgement", f"Failed for {a}: got {res.kind}")
                self.assertIsNotNone(res.response)

    def test_help_inquiries(self):
        helps = [
            "help", "help me", "what can you do", "what can you do?",
            "how do i use this", "commands", "show commands"
        ]
        for h in helps:
            with self.subTest(help=h):
                res = classify_intent(h)
                self.assertEqual(res.kind, "help", f"Failed for {h}: got {res.kind}")
                self.assertIsNotNone(res.response)

    def test_ambiguous_requests(self):
        ambiguous = [
            "", "   ", "pricing", "pricing.py", "discount", "test",
            "maybe", "hmm", "not sure", "bug", "files", "something"
        ]
        for amb in ambiguous:
            with self.subTest(ambiguous=amb):
                res = classify_intent(amb)
                self.assertEqual(res.kind, "ambiguous", f"Failed for '{amb}': got {res.kind}")
                self.assertIsNotNone(res.clarification)

    def test_questions(self):
        questions = [
            "how are you",
            "how are you doing",
            "are you doing fine",
            "are you ok",
            "what's up",
            "What does discounted_price do?",
            "How does pricing.py work?",
            "Why do the tests fail?",
            "Can you explain the discount formula?",
            "How do I fix the discount calculation?",
            "Where is the pricing calculation located?",
            "Explain pricing.py",
            "what happened?",
            "is the formula correct?",
        ]
        for q in questions:
            with self.subTest(question=q):
                res = classify_intent(q)
                self.assertEqual(res.kind, "question", f"Failed for {q}: got {res.kind}")

    def test_genuine_coding_tasks(self):
        coding = [
            "Fix the percentage discount calculation. Preserve the existing tests and public API.",
            "Fix discount",
            "Fix",
            "Inspect",
            "the discount formula is wrong, it should be price * (1 - discount/100)",
            "discounted_price should subtract the discount from price",
            "Make tests pass",
            "Make the test pass",
            "Can you fix the discount in pricing.py?",
            "Please update pricing.py to subtract the discount",
            "Refactor discounted_price to handle negative discounts",
            "hi, please fix the discount formula",
            "Change the calculation to subtract discount",
        ]
        for c in coding:
            with self.subTest(task=c):
                res = classify_intent(c)
                self.assertEqual(res.kind, "coding", f"Failed for {c}: got {res.kind}")
