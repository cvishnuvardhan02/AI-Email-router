import streamlit as st
import pandas as pd
import sqlite3

st.set_page_config(page_title="Email Analytics", layout="wide")
st.title("📊 Real-Time Sales Response Analytics")

conn = sqlite3.connect("analytics.db")
df = pd.read_sql("SELECT * FROM email_logs", conn)
conn.close()

if df.empty:
    st.info("Waiting for emails to arrive...")
else:
    # 5 Data Columns
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Emails Received", len(df))
    col2.metric("Opened/Read", df['read_time'].notna().sum())
    col3.metric("Pending Replies", df['replied_time'].isna().sum())

    avg = df['response_minutes'].mean()
    col4.metric("Avg Response Time", f"{avg:.1f} mins" if pd.notna(avg) else "N/A")

    meetings = (df['meeting_requested'] == 'Yes').sum() if 'meeting_requested' in df.columns else 0
    col5.metric("📅 Meetings Requested", int(meetings))

    st.divider()

    st.subheader("Leaderboard: Average Response Time by Rep")
    rep_stats = df.dropna(subset=['response_minutes']).groupby('assigned_name')['response_minutes'].mean().reset_index()
    if not rep_stats.empty:
        st.bar_chart(rep_stats.set_index('assigned_name'))
    else:
        st.write("No replies logged yet to generate chart.")

    st.subheader("Live Email Tracking Tracker")

    # Create beautiful status labels
    display_df = df.copy()
    display_df['Status'] = '📥 Unread'
    display_df.loc[display_df['read_time'].notna(), 'Status'] = '👀 Read'
    display_df.loc[display_df['replied_time'].notna(), 'Status'] = '✅ Replied'

    display_df['Notified'] = display_df['notification_sent'].apply(
        lambda v: '📤 Sent' if v == 1 else '⚠️ Failed'
    )
    display_df['Routed To'] = display_df['assigned_name'] + ' <' + display_df['assigned_rep'] + '>'

    # Sort so newest emails are at the top
    display_df = display_df.sort_values(by='received_time', ascending=False)

    # The summary and meeting details are shown here so anyone can see what an email
    # is about, and whether a meeting was requested, WITHOUT opening the email itself.
    st.dataframe(
        display_df[['Status', 'sender', 'Routed To', 'Notified', 'summary',
                     'meeting_requested', 'meeting_details',
                     'received_time', 'read_time', 'replied_time', 'response_minutes']],
        use_container_width=True
    )
