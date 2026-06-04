import streamlit as st
import requests
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

API = "http://localhost:8000"

st.set_page_config(
    page_title="PipelinePulse",
    page_icon="🔁",
    layout="wide"
)

st.title("🔁 PipelinePulse")
st.caption("Airflow Pipeline Monitoring Dashboard")

view = st.sidebar.radio("View", ["Engineer View", "Stakeholder View"])
st.sidebar.markdown("---")
st.sidebar.markdown("**DAGs**")

DAGS = ["dag_sales_pipeline", "dag_customer_etl", "dag_inventory_sync", "dag_reporting"]
selected_dag = st.sidebar.selectbox("Select DAG", DAGS)

if st.sidebar.button("Refresh Data"):
    st.rerun()

if view == "Engineer View":
    st.subheader("Pipeline Health Overview")

    summary = requests.get(f"{API}/summary").json()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Runs", summary["total_runs"])
    c2.metric("Successful", summary["success"])
    c3.metric("Failed", summary["failed"], delta=f"-{summary['failed']}", delta_color="inverse")
    c4.metric("Success Rate", f"{summary['success_rate']}%")

    st.markdown("---")
    st.subheader(f"DAG Run History: `{selected_dag}`")

    runs_data = requests.get(f"{API}/runs/{selected_dag}").json()
    runs = runs_data.get("runs", [])

    if runs:
        df = pd.DataFrame(runs)
        df["start_date"] = pd.to_datetime(df["start_date"])
        df["duration_minutes"] = df["duration_seconds"] / 60

        color_map = {"success": "#2ecc71", "failed": "#e74c3c", "running": "#3498db"}
        df["color"] = df["state"].map(color_map).fillna("#95a5a6")

        fig = px.bar(
            df,
            x="start_date",
            y="duration_minutes",
            color="state",
            color_discrete_map={"success": "#2ecc71", "failed": "#e74c3c", "running": "#3498db"},
            title="Run Duration by State",
            labels={"duration_minutes": "Duration (min)", "start_date": "Run Time"}
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("**Recent Runs**")
        display_df = df[["run_id", "state", "start_date", "duration_minutes"]].copy()
        display_df["duration_minutes"] = display_df["duration_minutes"].round(2)
        display_df = display_df.sort_values("start_date", ascending=False).head(10)
        st.dataframe(display_df, use_container_width=True)

        failed_runs = df[df["state"] == "failed"]["run_id"].tolist()
        if failed_runs:
            st.markdown("---")
            st.subheader("AI Failure Analysis")
            selected_run = st.selectbox("Select failed run to analyze", failed_runs)
            if st.button("Analyze with Gemini"):
                with st.spinner("Analyzing failure..."):
                    result = requests.get(f"{API}/ai/explain/{selected_dag}/{selected_run}").json()
                    st.markdown("### Gemini Analysis")
                    st.markdown(result.get("insight", "No insight available."))
        else:
            st.success("No failed runs for this DAG.")
    else:
        st.info("No run data available yet.")

else:
    st.subheader("Pipeline Status Summary")
    st.caption("Business-friendly view — no technical jargon")

    summary = requests.get(f"{API}/summary").json()

    total = summary["total_runs"]
    success_rate = summary["success_rate"]

    if success_rate >= 90:
        status_color = "green"
        status_icon = "✅"
        status_text = "All systems operational"
    elif success_rate >= 70:
        status_color = "orange"
        status_icon = "⚠️"
        status_text = "Some pipelines need attention"
    else:
        status_color = "red"
        status_icon = "🚨"
        status_text = "Critical pipeline issues detected"

    st.markdown(f"## {status_icon} Overall Status: :{status_color}[{status_text}]")

    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=success_rate,
            title={"text": "Pipeline Success Rate (%)"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#2ecc71"},
                "steps": [
                    {"range": [0, 70], "color": "#fadbd8"},
                    {"range": [70, 90], "color": "#fef9e7"},
                    {"range": [90, 100], "color": "#eafaf1"},
                ]
            }
        ))
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.markdown("### Pipeline Status by DAG")
        for dag in DAGS:
            runs_data = requests.get(f"{API}/runs/{dag}").json()
            runs = runs_data.get("runs", [])
            if runs:
                total_dag = len(runs)
                failed_dag = sum(1 for r in runs if r["state"] == "failed")
                rate = round(((total_dag - failed_dag) / total_dag) * 100, 1)
                icon = "✅" if rate >= 90 else "⚠️" if rate >= 70 else "🚨"
                st.markdown(f"{icon} **{dag}** — {rate}% success ({total_dag} runs)")
            else:
                st.markdown(f"⏳ **{dag}** — No data yet")

    st.markdown("---")
    st.subheader(f"AI Status Summary: `{selected_dag}`")
    if st.button("Generate Business Summary"):
        with st.spinner("Generating summary..."):
            result = requests.get(f"{API}/ai/stakeholder/{selected_dag}").json()
            st.info(result.get("summary", "No summary available."))
