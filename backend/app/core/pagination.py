MAX_PAGE_SIZE = 500


def clamp_pagination(page: int = 1, page_size: int = 50, *, max_page_size: int = MAX_PAGE_SIZE) -> tuple[int, int, int]:
    safe_page = max(1, int(page or 1))
    safe_size = max(1, min(int(page_size or 50), int(max_page_size or MAX_PAGE_SIZE)))
    return safe_page, safe_size, (safe_page - 1) * safe_size
