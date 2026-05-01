from confluence_pdf.models import Page
from confluence_pdf.tree import list_space_tree


class FakeTreeClient:
    def resolve_page_by_title(self, space_key: str, title: str) -> Page:
        assert space_key == "DOC"
        assert title == "Child"
        return Page(id="2", title="Child")

    def list_space_root_pages(self, space_key: str) -> list[Page]:
        assert space_key == "DOC"
        return [Page(id="1", title="Root")]

    def list_child_pages(self, page_id: str) -> list[Page]:
        return {
            "1": [Page(id="2", title="Child"), Page(id="3", title="Other Child")],
            "2": [Page(id="4", title="Grandchild")],
            "3": [],
        }[page_id]


def test_list_space_tree_stops_at_requested_depth() -> None:
    tree_pages = list_space_tree(FakeTreeClient(), space_key="DOC", max_depth=2)  # type: ignore[arg-type]

    assert [(tree_page.page.title, tree_page.depth, tree_page.path) for tree_page in tree_pages] == [
        ("Root", 1, ("Root",)),
        ("Child", 2, ("Root", "Child")),
        ("Other Child", 2, ("Root", "Other Child")),
    ]


def test_list_space_tree_can_start_at_root_title() -> None:
    tree_pages = list_space_tree(  # type: ignore[arg-type]
        FakeTreeClient(),
        space_key="DOC",
        max_depth=2,
        root_title="Child",
    )

    assert [(tree_page.page.title, tree_page.depth, tree_page.path) for tree_page in tree_pages] == [
        ("Child", 1, ("Child",)),
        ("Grandchild", 2, ("Child", "Grandchild")),
    ]
