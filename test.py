import requests
from bs4 import BeautifulSoup


def decode_secret_message(url: str) -> None:
    """
    Fetches a published Google Doc containing x-coordinate,
    character, and y-coordinate data, then prints the decoded
    character grid.
    """

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    characters = {}
    max_x = 0
    max_y = 0

    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])

        if len(cells) < 3:
            continue

        x_text = cells[0].get_text(strip=True)
        character = cells[1].get_text(strip=True)
        y_text = cells[2].get_text(strip=True)

        # Skip the header row or any non-data rows.
        try:
            x = int(x_text)
            y = int(y_text)
        except ValueError:
            continue

        characters[(x, y)] = character

        max_x = max(max_x, x)
        max_y = max(max_y, y)

    if not characters:
        raise ValueError("No coordinate data found in the document.")

    # y increases upward in the document, while terminal output
    # is printed from top to bottom, so iterate y in reverse.
    for y in range(max_y, -1, -1):
        line = "".join(
            characters.get((x, y), " ")
            for x in range(max_x + 1)
        )
        print(line)


decode_secret_message(
    "https://docs.google.com/document/d/e/2PACX-1vSvM5gDlNvt7npYHhp_XfsJvuntUhq184By5xO_pA4b_gCWeXb6dM6ZxwN8rE6S4ghUsCj2VKR21oEP/pub"
)