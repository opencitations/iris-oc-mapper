from datetime import date

import plotly.express as px
import plotly.graph_objects as go
import polars as pl


def generate_iris_sankey(stats: dict) -> str:
    extra_pids = max(stats["found_pids"] - stats["with_pids"], 0)

    labels = [
        "IRIS Records",  # 0
        "With PIDs",  # 1
        "Without PIDs",  # 2
        "PIDs found",  # 3
        "",  # 4
        "DOIs",  # 5
        "PMIDs",  # 6
        "ISBNs",  # 7
        "Valid DOIs",  # 14
        "Valid PMIDs",  # 15
        "Valid ISBNs",  # 16
    ]
    sources = [
        0,  # IRIS -> With PIDs
        0,  # IRIS -> Without PIDs
        1,  # With PIDs -> PIDs found
        4,  # Extra found PIDs -> PIDs found
        3,  # PIDs found -> DOIs
        3,  # PIDs found -> PMIDs
        3,  # PIDs found -> ISBNs
        5,  # DOIs -> Valid DOIs
        6,  # PMIDs -> Valid PMIDs
        7,  # ISBNs -> Valid ISBNs
    ]
    targets = [
        1,
        2,
        3,
        3,
        5,
        6,
        7,
        8,
        9,
        10,
    ]
    values = [
        stats["with_pids"],
        stats["without_pids"],
        stats["with_pids"],
        extra_pids,
        stats["found_dois"],
        stats["found_pmids"],
        stats["found_isbns"],
        stats["valid_dois"],
        stats["valid_pmids"],
        stats["valid_isbns"],
    ]
    # --- Colors ---
    node_colors = [
        "#4B0082",  # IRIS Records
        "#6A5ACD",  # With PIDs
        "#9370DB",  # Without PIDs
        "#8A2BE2",  # PIDs found
        "rgba(0,0,0,0)",  # hidden node
        "#7B68EE",  # DOIs
        "#4682B4",  # PMIDs
        "#5F9EA0",  # ISBNs
        "#4169E1",  # Valid DOIs
        "#00CED1",  # Valid PMIDs
        "#20B2AA",  # Valid ISBNs
    ]
    link_colors = ["rgba(106,90,205,0.3)" if n != "" else "rgba(0,0,0,0)" for n in labels[1:]]
    x_positions = [
        0.0,  # IRIS Records
        0.3,  # With PIDs
        0.3,  # Without PIDs
        0.5,  # PIDs found
        0.4,
        0.7,  # DOIs
        0.7,  # PMIDs
        0.7,  # ISBNs
        0.9,  # Valid DOIs
        0.9,  # Valid PMIDs
        0.9,  # Valid ISBNs
    ]
    y_positions = [
        0.5,  # IRIS Records
        0.3,  # With PIDs
        0.85,  # Without any PID
        0.5,  # PIDs found
        0.9,
        0.2,  # DOIs
        0.5,  # PMIDs
        0.8,  # ISBNs
        0.2,  # Valid DOIs
        0.5,  # Valid PMIDs
        0.8,  # Valid ISBNs
    ]

    fig = go.Figure(
        data=[
            go.Sankey(
                node=dict(
                    pad=25,
                    thickness=25,
                    line=dict(color="white", width=1),
                    label=labels,
                    color=node_colors,
                    x=x_positions,
                    y=y_positions,
                ),
                link=dict(
                    source=sources,
                    target=targets,
                    value=values,
                    color=link_colors,
                ),
                valueformat=",d",
            )
        ]
    )

    fig.update_layout(
        font=dict(size=14, family="Arial"),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=20, r=20, t=20, b=20),
    )

    return fig.to_html(full_html=False)


def generate_temporal_distribution(df: pl.DataFrame) -> str:
    df_years = (
        df.group_by("DATE_ISSUED_YEAR")
        .agg(pl.len())
        .filter(
            pl.col("DATE_ISSUED_YEAR").is_not_null()
            & (1800 <= pl.col("DATE_ISSUED_YEAR"))
            & (pl.col("DATE_ISSUED_YEAR") <= date.today().year + 10)
        )
        .sort("DATE_ISSUED_YEAR")
    )

    fig = px.line(
        df_years,
        x=df_years["DATE_ISSUED_YEAR"].to_list(),
        y=df_years["len"].to_list(),
        markers=True,
        labels={"x": "Year", "y": "Number of Records"},
        title="IRIS – Number of Items by Year Published",
    )

    fig.update_traces(
        line=dict(color="steelblue", width=2),
        hovertemplate="<b>%{x}</b><br>Records: %{y:,}<extra></extra>",
    )

    fig.update_layout(
        template="plotly_white",
        xaxis=dict(tickangle=-45, showgrid=True, gridcolor="lightgray"),
        yaxis=dict(showgrid=True, gridcolor="lightgray", title="Number of Records"),
        hovermode="x unified",
    )

    return fig.to_html(full_html=False)


def generate_coverage_plot(in_meta, iris, no_pid) -> str:
    iris_in_meta = in_meta.df.height
    iris_not_in_meta = iris.df.height - iris_in_meta
    total = iris.df.height

    # perc_in_meta = iris_in_meta / total * 100
    perc_not_in_meta = iris_not_in_meta / total * 100

    data = {
        "Category": ["In OC", "Not in OC"],
        "Count": [iris_in_meta, iris_not_in_meta],
    }

    df = pl.DataFrame(data)

    fig = px.pie(
        df,
        names="Category",
        values="Count",
        color="Category",
        color_discrete_map={
            "In OC": "#AA5BF9",
            "Not in OC": "#cccccc",
        },
        title="IRIS Publications Coverage in OC Meta",
        hole=0.5,
    )

    fig.update_traces(
        textinfo="percent+label",
        textposition="inside",
        textfont=dict(size=15, family="Arial", weight="bold", color=["black", "#cccccc"]),
        hovertemplate="%{label}: %{value} records<br>(%{percent})",
        insidetextorientation="horizontal",
        marker=dict(line=dict(color="white", width=2)),
        sort=False,
    )

    fig.add_trace(
        go.Pie(
            labels=["Rest of IRIS not in OC", "No PID"],
            values=[iris.df.height - no_pid.df.height, no_pid.df.height],
            hole=0.8,
            marker=dict(colors=["rgba(0,0,0,0)", "#E69B1A"], line=dict(color="white", width=0)),
            textinfo="percent+label",
            textposition="inside",
            texttemplate=["", "%{label}<br>%{percent}"],
            sort=False,
            showlegend=False,
            hovertemplate=[
                "<extra></extra>",
                "%{label}: %{value} records<br>(%{percent})<extra></extra>",
            ],
            rotation=-0.5,
        )
    )

    fig.add_annotation(
        text=f"<b>{iris_in_meta / total:.1%}</b><br>"
        f"<span style='font-size:14px;color:#666;'>"
        f"coverage in OC Meta</span>",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=18, family="Arial"),
    )

    fig.update_layout(
        title_font=dict(size=18, family="Arial", color="#2c3e50", weight="bold"),
        showlegend=False,
        height=500,
        width=500,
        margin=dict(l=40, r=40, t=40, b=20),
    )

    def _map_percentage_to_x(value, in_min=0.35, in_max=0.45, out_min=0.4, out_max=0.5):
        value = max(min(value, in_max), in_min)
        return out_min + (value - in_min) * (out_max - out_min) / (in_max - in_min)

    no_pid_pct = no_pid.df.height / iris.df.height
    fig.add_annotation(
        x=_map_percentage_to_x(no_pid_pct),
        y=0.1,
        text=f"Not in OC<br>{perc_not_in_meta:.1f}%",
        showarrow=False,
        font=dict(size=15, family="Arial", color="black", weight="bold"),
    )

    return fig.to_html(full_html=False)
