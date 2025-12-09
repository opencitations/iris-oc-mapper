import html
from datetime import date

import polars as pl


def df_to_html(df: pl.DataFrame) -> str:
    """Convert a Polars DataFrame to an HTML table."""
    headers = "".join(f"<th>{html.escape(col)}</th>" for col in df.columns)

    rows_html = ""
    for row in df.rows():
        cells = []
        for val in row:
            if isinstance(val, int):
                val = f"{val:,}"
            elif isinstance(val, str):
                val = html.escape(val)
            cells.append(f"<td>{val}</td>")
        rows_html += "<tr>" + "".join(cells) + "</tr>"

    return f"<table><thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>"


def get_implausible_years(df: pl.DataFrame) -> list[dict[str, int]]:
    """Identify implausible years in the 'DATE_ISSUED_YEAR' column of the DataFrame.

    Args:
        df (pl.DataFrame): Input DataFrame containing a 'DATE_ISSUED_YEAR' column.

    Returns:
        list[dict[str, int]]: List of dictionaries with implausible years and their counts.
    """
    return (
        df.group_by("DATE_ISSUED_YEAR")
        .agg(pl.len())
        .sort("DATE_ISSUED_YEAR")
        .filter(
            pl.col("DATE_ISSUED_YEAR").is_null()
            | (pl.col("DATE_ISSUED_YEAR") < 1800)
            | (pl.col("DATE_ISSUED_YEAR") > date.today().year + 10)
        )
        .to_dicts()
    )
