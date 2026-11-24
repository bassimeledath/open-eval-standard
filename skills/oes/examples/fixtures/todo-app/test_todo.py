import unittest

from todo import TodoList


class TodoTest(unittest.TestCase):
    def test_add(self):
        todos = TodoList()
        todos.add("buy milk")
        self.assertEqual(len(todos.items), 1)

    def test_complete(self):
        todos = TodoList()
        todos.add("buy milk")
        todos.complete("buy milk")
        self.assertEqual(todos.pending(), [])

    def test_complete_missing(self):
        with self.assertRaises(KeyError):
            TodoList().complete("nothing")


if __name__ == "__main__":
    unittest.main()
