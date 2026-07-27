from collections import deque

class TrieNode:
    def __init__(self):
        self.children = {}
        self.fail = None
        self.output = []  # 元素格式为 (keyword, value)

class AhoCorasick:
    def __init__(self):
        self.root = TrieNode()

    def add_keyword(self, keyword: str, value=None):
        """
        向字典树中添加一个关键词及其关联的值
        """
        if not keyword:
            return
        node = self.root
        for char in keyword:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.output.append((keyword, value))

    def make_automaton(self):
        """
        使用 BFS (广度优先搜索) 算法构建失败指针 (fail links) 并合并输出项
        """
        queue = deque()
        # 将第一层的结点的失败指针都指向根节点
        for char, child in self.root.children.items():
            child.fail = self.root
            queue.append(child)

        while queue:
            current_node = queue.popleft()

            for char, child in current_node.children.items():
                fail_node = current_node.fail
                # 沿失败路径回溯，直到找到一个节点拥有相同的字符子节点
                while fail_node is not None and char not in fail_node.children:
                    fail_node = fail_node.fail
                
                if fail_node is not None:
                    child.fail = fail_node.children[char]
                else:
                    child.fail = self.root
                
                # 如果失败节点的输出列表不为空，合并到当前节点的输出列表中以防漏匹配
                if child.fail.output:
                    child.output.extend(child.fail.output)

                queue.append(child)

    def search_all(self, text: str):
        """
        在文本中扫描匹配所有注册的关键词
        返回生成器，每次 yield 包含: (start_index, end_index, keyword, value)
        """
        if not text:
            return
        node = self.root
        for i, char in enumerate(text):
            while node is not None and char not in node.children:
                node = node.fail
            
            if node is None:
                node = self.root
                continue
                
            node = node.children[char]
            for keyword, value in node.output:
                yield i - len(keyword) + 1, i, keyword, value
