"""A tiny todo list, the starting point for the coding-agent example."""


class TodoList:
    def __init__(self):
        self.items = []

    def add(self, title):
        item = {"title": title, "done": False}
        self.items.append(item)
        return item

    def complete(self, title):
        for item in self.items:
            if item["title"] == title:
                item["done"] = True
                return item
        raise KeyError(title)

    def pending(self):
        return [i for i in self.items if not i["done"]]
