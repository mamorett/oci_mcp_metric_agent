import streamlit as st
import requests
import json
import datetime
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, List, Optional
from dotenv import load_dotenv
import os
from openai import OpenAI


# Configuration
load_dotenv()  # Load environment variables from .env file

# NVIDIA NIM Configuration
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"  # or your NIM endpoint
NIM_MODEL = "mistralai/mistral-nemotron"  # or your preferred NIM model
NIM_API_KEY = os.environ.get("NIM_API_KEY", "")

# FastAPI Backend Configuration
FASTAPI_BASE_URL = "http://localhost:8000"  # Your FastAPI server URL

class OCIStreamlitApp:
    def __init__(self):
        self.nim_base_url = NIM_BASE_URL
        self.nim_api_key = NIM_API_KEY
        self.nim_model = NIM_MODEL
        self.fastapi_base_url = FASTAPI_BASE_URL
        
    def check_backend_connection(self) -> bool:
        """Check if the FastAPI backend is running"""
        try:
            response = requests.get(f"{self.fastapi_base_url}/", timeout=5)
            return response.status_code == 200
        except Exception as e:
            st.error(f"Cannot connect to backend server: {e}")
            return False
    
    def get_compartments(self, parent_compartment_id: Optional[str] = None) -> Optional[List[Dict]]:
        """Get list of OCI compartments from FastAPI backend"""
        try:
            params = {}
            if parent_compartment_id:
                params['parent_compartment_id'] = parent_compartment_id
                
            response = requests.get(
                f"{self.fastapi_base_url}/compartments",
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                compartments = data.get("compartments", [])
                return compartments
            else:
                st.error(f"Error fetching compartments: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            st.error(f"Error connecting to backend: {e}")
            return None
    
    def get_instances(self, compartment_id: str) -> Optional[List[Dict]]:
        """Get list of OCI compute instances from FastAPI backend"""
        try:
            response = requests.get(
                f"{self.fastapi_base_url}/instances",
                params={'compartment_id': compartment_id},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                instances = data.get("instances", [])
                return instances
            else:
                st.error(f"Error fetching instances: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            st.error(f"Error connecting to backend: {e}")
            return None
    
    def get_all_metrics_data(self, instance_id: str, compartment_id: str, hours_back: int = 1) -> Optional[Dict]:
        """Get all metrics data for an instance from FastAPI backend"""
        try:
            response = requests.get(
                f"{self.fastapi_base_url}/instances/{instance_id}/metrics",
                params={"compartment_id": compartment_id, "hours_back": hours_back},
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                st.error(f"Error fetching metrics: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            st.error(f"Error fetching metrics: {e}")
            return None
    
    def get_metric_data(self, metric_name: str, instance_id: str, compartment_id: str, hours_back: int = 1) -> Optional[Dict]:
        """Get historical data for a specific metric from FastAPI backend"""
        try:
            response = requests.get(
                f"{self.fastapi_base_url}/instances/{instance_id}/metrics/{metric_name}",
                params={"compartment_id": compartment_id, "hours_back": hours_back},
                timeout=60
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                st.error(f"Error fetching metric data: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            st.error(f"Error fetching metric data: {e}")
            return None
    
    def get_available_metrics(self) -> Optional[List[str]]:
        """Get list of available metrics from FastAPI backend"""
        try:
            response = requests.get(f"{self.fastapi_base_url}/metrics", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("available_metrics", [])
            else:
                return None
                
        except Exception as e:
            st.error(f"Error fetching available metrics: {e}")
            return None
    
    def query_nvidia_nim(self, prompt: str, context: str = "") -> str:
        """Query NVIDIA NIM with context about OCI metrics using OpenAI library"""
        try:
            # Initialize OpenAI client for NVIDIA NIM
            client = OpenAI(
                base_url=self.nim_base_url,  # Should be "https://integrate.api.nvidia.com/v1"
                api_key=self.nim_api_key
            )
            
            full_prompt = f"""
    You are an expert in Oracle Cloud Infrastructure (OCI) monitoring and compute agent metrics analysis. 
    You have access to real-time monitoring data from OCI compute instances.

    The following metrics are available:
    - CpuUtilization: CPU usage percentage
    - MemoryUtilization: Memory usage percentage  
    - LoadAverage: System load average
    - DiskIopsRead: Disk read IOPS (rate per second)
    - DiskIopsWritten: Disk write IOPS (rate per second)

    Context about the current metrics data:
    {context}

    User question: {prompt}

    Please provide a helpful and accurate response based on the monitoring data provided.
    Focus on practical insights and recommendations for system monitoring and performance optimization.
    """
            
            completion = client.chat.completions.create(
                model=self.nim_model,
                messages=[
                    {
                        "role": "system",
                        "content": "detailed thinking on"
                    },                    
                    {
                        "role": "user",
                        "content": full_prompt
                    }
                ],
                temperature=0.6,
                top_p=0.7,
                max_tokens=4096,
                frequency_penalty=0,
                presence_penalty=0,
                stream=True
            )
            
            # Collect streaming response
            response_content = ""
            for chunk in completion:
                if chunk.choices[0].delta.content is not None:
                    response_content += chunk.choices[0].delta.content
            
            return response_content
            
        except Exception as e:
            return f"Error querying NVIDIA NIM: {e}"


# Global helper functions for consistent IOPS handling
def calculate_iops_rate(datapoints):
    """Calculate IOPS rate from cumulative counter datapoints - simplified version"""
    if not datapoints or len(datapoints) < 2:
        return None
    
    try:
        # Get the last few points to work with
        recent_points = datapoints[-5:]  # Use last 5 points for more stability
        
        if len(recent_points) < 2:
            return None
        
        # Find two points with valid data
        for i in range(len(recent_points) - 1, 0, -1):
            current = recent_points[i]
            previous = recent_points[i-1]
            
            current_value = current.get("value")
            previous_value = previous.get("value")
            
            if current_value is None or previous_value is None:
                continue
                
            # Simple approach: assume datapoints are roughly 1 minute apart
            # This is typical for OCI monitoring metrics
            time_diff_minutes = 1  # Assume 1 minute intervals
            value_diff = current_value - previous_value
            
            if value_diff >= 0:  # Only return if we have a positive difference
                # Convert to per-second rate
                return value_diff / (time_diff_minutes * 60)
        
        return None
        
    except Exception as e:
        print(f"Error in IOPS calculation: {e}")
        return None

def is_cumulative_metric(metric_name):
    """Check if a metric is cumulative (counter) type"""
    cumulative_metrics = ["DiskIopsRead", "DiskIopsWritten"]
    return metric_name in cumulative_metrics

def convert_cumulative_to_rates(datapoints):
    """Convert cumulative datapoints to rate datapoints"""
    if not datapoints or len(datapoints) < 2:
        return []
    
    rate_datapoints = []
    
    for i in range(1, len(datapoints)):
        current = datapoints[i]
        previous = datapoints[i-1]
        
        current_value = current.get("value")
        previous_value = previous.get("value")
        
        if current_value is None or previous_value is None:
            continue
        
        # Calculate rate (assuming 1 minute intervals)
        time_diff_minutes = 1
        value_diff = current_value - previous_value
        
        if value_diff >= 0:  # Handle counter resets
            rate = value_diff / (time_diff_minutes * 60)  # Convert to per-second
            
            rate_datapoints.append({
                "timestamp": current.get("timestamp"),
                "value": rate
            })
    
    return rate_datapoints


def main():
    st.set_page_config(
        page_title="OCI Compute Metrics Monitor",
        page_icon="☁️",
        layout="wide"
    )
    
    st.title("☁️ Oracle Cloud Infrastructure Compute Metrics Monitor")
    st.markdown("Monitor your OCI compute instances with compute agent metrics and AI-powered insights")
    
    app = OCIStreamlitApp()
    
    # Sidebar for configuration
    st.sidebar.header("Configuration")
    
    # Backend connection status
    st.sidebar.subheader("🔧 Backend Connection")
    if st.sidebar.button("Check Backend Connection"):
        if app.check_backend_connection():
            st.sidebar.success("✅ Backend Connected")
        else:
            st.sidebar.error("❌ Backend Not Connected")
    
    # Check backend connection on startup
    if not app.check_backend_connection():
        st.error("⚠️ Cannot connect to the FastAPI backend server!")
        st.info(f"Please ensure your FastAPI server is running at: {app.fastapi_base_url}")
        st.code("python your_fastapi_server.py")
        return
    
    # Compartment selection
    st.sidebar.subheader("🗂️ Compartment Selection")
    
    # Get compartments
    with st.spinner("Loading compartments..."):
        compartments = app.get_compartments()
    
    if not compartments:
        st.error("Failed to retrieve OCI compartments")
        return
    
    # Create compartment selector
    compartment_options = {f"{comp['name']} ({comp['id'][:20]}...)": comp['id'] for comp in compartments}
    selected_compartment_display = st.sidebar.selectbox("Select Compartment", list(compartment_options.keys()))
    selected_compartment_id = compartment_options[selected_compartment_display]
    
    st.sidebar.info(f"Selected compartment: {selected_compartment_id}")
    
    # Get instances from selected compartment
    with st.spinner("Loading instances from selected compartment..."):
        instances = app.get_instances(selected_compartment_id)
    
    if not instances:
        st.error("Failed to retrieve OCI compute instances from selected compartment")
        return
    
    if len(instances) == 0:
        st.warning(f"No compute instances found in the selected compartment")
        st.info("Try selecting a different compartment or check if instances exist in this compartment")
        return
    
    st.success(f"✅ Found {len(instances)} compute instances in selected compartment")
    
    # Show instance states
    running_instances = [i for i in instances if i['lifecycle_state'] == 'RUNNING']
    if len(running_instances) == 0:
        st.warning("No RUNNING instances found in this compartment")
        st.info("Metrics are only available for RUNNING instances")
    
    # Instance selection
    st.sidebar.subheader("🖥️ Instance Selection")
    instance_options = {f"{instance['display_name']} ({instance['lifecycle_state']})": instance['id'] for instance in instances}
    selected_instance_display = st.sidebar.selectbox("Select Compute Instance", list(instance_options.keys()))
    selected_instance_id = instance_options[selected_instance_display]
    
    # Find selected instance info
    selected_instance_info = next((i for i in instances if i['id'] == selected_instance_id), None)
    
    if selected_instance_info and selected_instance_info['lifecycle_state'] != 'RUNNING':
        st.sidebar.warning(f"⚠️ Selected instance is {selected_instance_info['lifecycle_state']}")
        st.sidebar.info("Metrics are only available for RUNNING instances")
    
    # Time range selection
    hours_back = st.sidebar.slider("Hours of data to retrieve", 1, 24, 1)
    
    # Auto-refresh option
    auto_refresh = st.sidebar.checkbox("Auto-refresh (30s)")
    if auto_refresh:
        time.sleep(30)
        st.rerun()
    
    # NVIDIA NIM Configuration in sidebar
    st.sidebar.subheader("🤖 NVIDIA NIM Settings")
    
    # Allow users to override NIM settings
    nim_base_url = st.sidebar.text_input("NIM Base URL", value=NIM_BASE_URL)
    nim_model = st.sidebar.selectbox("NIM Model", [
        "nvidia/llama-3.1-nemotron-nano-8b-v1",
        "mistralai/mistral-nemotron",
        "nvidia/llama-3.1-nemotron-nano-4b-v1.1",
        "nvidia/llama-3.3-nemotron-super-49b-v1",
        "mistralai/mixtral-8x7b-instruct-v0.1"
    ], index=0)
    
    # Update app configuration
    app.nim_base_url = nim_base_url
    app.nim_model = nim_model
    
    # Main content tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "📈 Detailed Metrics", "🤖 AI Assistant", "🖥️ Instance Info"])
    
    with tab1:
        st.header("OCI Compute Agent Metrics Dashboard")
        
        if selected_instance_info and selected_instance_info['lifecycle_state'] != 'RUNNING':
            st.warning(f"Instance is {selected_instance_info['lifecycle_state']} - metrics not available")
            return
        
        # Get all metrics data
        with st.spinner("Loading metrics data..."):
            metrics_data = app.get_all_metrics_data(selected_instance_id, selected_compartment_id, hours_back)
        
        if not metrics_data:
            st.error("Failed to retrieve metrics data")
            return
        
        metrics = metrics_data.get("metrics", {})
        
        # Create metrics grid
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # CPU metrics
            st.subheader("🔥 CPU")
            cpu_data = metrics.get("CpuUtilization", {})
            load_data = metrics.get("LoadAverage", {})
            
            # Get latest values from datapoints
            cpu_util = None
            if cpu_data.get("datapoints"):
                cpu_util = cpu_data["datapoints"][-1].get("value")
            
            load_avg = None
            if load_data.get("datapoints"):
                load_avg = load_data["datapoints"][-1].get("value")
            
            if cpu_util is not None:
                st.metric("CPU Utilization", f"{cpu_util:.1f}%")
            else:
                st.metric("CPU Utilization", "No data")
                
            if load_avg is not None:
                st.metric("Load Average", f"{load_avg:.2f}")
            else:
                st.metric("Load Average", "No data")
        
        with col2:
            # Memory metrics
            st.subheader("💾 Memory")
            mem_data = metrics.get("MemoryUtilization", {})
            
            mem_util = None
            if mem_data.get("datapoints"):
                mem_util = mem_data["datapoints"][-1].get("value")
            
            if mem_util is not None:
                st.metric("Memory Utilization", f"{mem_util:.1f}%")
            else:
                st.metric("Memory Utilization", "No data")
        
        with col3:
            # Disk metrics - Calculate rates from cumulative counters
            st.subheader("💿 Disk I/O")
            disk_read_data = metrics.get("DiskIopsRead", {})
            disk_write_data = metrics.get("DiskIopsWritten", {})
            
            # Calculate current IOPS rates
            disk_read_rate = calculate_iops_rate(disk_read_data.get("datapoints", []))
            disk_write_rate = calculate_iops_rate(disk_write_data.get("datapoints", []))
            
            if disk_read_rate is not None:
                st.metric("Disk Read IOPS", f"{disk_read_rate:.1f}/sec")
            else:
                st.metric("Disk Read IOPS", "No data")
                
            if disk_write_rate is not None:
                st.metric("Disk Write IOPS", f"{disk_write_rate:.1f}/sec")
            else:
                st.metric("Disk Write IOPS", "No data")
            
            # Optional: Show cumulative totals as well
            if disk_read_data.get("datapoints"):
                total_reads = disk_read_data["datapoints"][-1].get("value", 0)
                st.caption(f"Total reads: {total_reads:,.0f}")
            
            if disk_write_data.get("datapoints"):
                total_writes = disk_write_data["datapoints"][-1].get("value", 0)
                st.caption(f"Total writes: {total_writes:,.0f}")

        
        # Status indicators
        st.subheader("🚦 System Health")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if cpu_util is not None:
                if cpu_util > 80:
                    st.error(f"🔴 High CPU Utilization: {cpu_util:.1f}%")
                elif cpu_util > 60:
                    st.warning(f"🟡 Moderate CPU Utilization: {cpu_util:.1f}%")
                else:
                    st.success(f"🟢 Normal CPU Utilization: {cpu_util:.1f}%")
            else:
                st.info("🔵 CPU data not available")
        
        with col2:
            if mem_util is not None:
                if mem_util > 85:
                    st.error(f"🔴 High Memory Utilization: {mem_util:.1f}%")
                elif mem_util > 70:
                    st.warning(f"🟡 Moderate Memory Utilization: {mem_util:.1f}%")
                else:
                    st.success(f"🟢 Normal Memory Utilization: {mem_util:.1f}%")
            else:
                st.info("🔵 Memory data not available")
        
        with col3:
            if load_avg is not None:
                if load_avg > 2.0:
                    st.error(f"🔴 High Load Average: {load_avg:.2f}")
                elif load_avg > 1.0:
                    st.warning(f"🟡 Moderate Load Average: {load_avg:.2f}")
                else:
                    st.success(f"🟢 Normal Load Average: {load_avg:.2f}")
            else:
                st.info("🔵 Load average data not available")
    
    with tab2:
        st.header("Detailed Metrics Analysis")
        
        if selected_instance_info and selected_instance_info['lifecycle_state'] != 'RUNNING':
            st.warning(f"Instance is {selected_instance_info['lifecycle_state']} - metrics not available")
            return
        
        # Get available metrics from backend
        available_metrics = app.get_available_metrics()
        if not available_metrics:
            available_metrics = [
                "CpuUtilization", "MemoryUtilization", "LoadAverage",
                "DiskIopsRead", "DiskIopsWritten"
            ]
        
        selected_metric = st.selectbox("Select metric for detailed analysis", available_metrics)
        
        # Get detailed metric data
        with st.spinner(f"Loading {selected_metric} data..."):
            detailed_data = app.get_metric_data(selected_metric, selected_instance_id, selected_compartment_id, hours_back)
        
        if detailed_data and detailed_data.get("datapoints"):
            datapoints = detailed_data["datapoints"]
            
            # Handle cumulative metrics (IOPS) differently
            if is_cumulative_metric(selected_metric):
                st.info(f"📊 {selected_metric} is a cumulative counter. Showing rate calculations (operations per second).")
                
                # Convert cumulative data to rates
                rate_datapoints = convert_cumulative_to_rates(datapoints)
                
                if rate_datapoints:
                    # Create DataFrame for plotting rates
                    df = pd.DataFrame([
                        {
                            "timestamp": datetime.datetime.fromisoformat(dp["timestamp"].replace('Z', '+00:00')),
                            "value": dp.get("value", 0)
                        }
                        for dp in rate_datapoints
                    ])
                    
                    # Sort by timestamp
                    df = df.sort_values('timestamp')
                    
                    # Plot the rate data
                    fig = px.line(df, x="timestamp", y="value", 
                                 title=f"{selected_metric} Rate over time",
                                 labels={"value": f"{selected_metric} (ops/sec)", "timestamp": "Time"})
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Statistics for rates
                    st.subheader("Rate Statistics (ops/sec)")
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Average Rate", f"{df['value'].mean():.2f}")
                    with col2:
                        st.metric("Maximum Rate", f"{df['value'].max():.2f}")
                    with col3:
                        st.metric("Minimum Rate", f"{df['value'].min():.2f}")
                    with col4:
                        st.metric("Current Rate", f"{df['value'].iloc[-1]:.2f}")
                    
                    # Also show cumulative totals
                    st.subheader("Cumulative Totals")
                    cumulative_df = pd.DataFrame([
                        {
                            "timestamp": datetime.datetime.fromisoformat(dp["timestamp"].replace('Z', '+00:00')),
                            "value": dp.get("value", 0)
                        }
                        for dp in datapoints
                    ])
                    cumulative_df = cumulative_df.sort_values('timestamp')
                    
                    fig_cumulative = px.line(cumulative_df, x="timestamp", y="value", 
                                           title=f"{selected_metric} Cumulative Total over time",
                                           labels={"value": f"{selected_metric} (total ops)", "timestamp": "Time"})
                    st.plotly_chart(fig_cumulative, use_container_width=True)
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Total Operations", f"{cumulative_df['value'].iloc[-1]:,.0f}")
                    with col2:
                        total_increase = cumulative_df['value'].iloc[-1] - cumulative_df['value'].iloc[0]
                        st.metric("Operations in Period", f"{total_increase:,.0f}")
                    
                else:
                    st.warning("Unable to calculate rates - insufficient data points")
                    
            else:
                # Handle regular (non-cumulative) metrics
                # Create DataFrame for plotting
                df = pd.DataFrame([
                    {
                        "timestamp": datetime.datetime.fromisoformat(dp["timestamp"].replace('Z', '+00:00')),
                        "value": dp.get("value", 0)
                    }
                    for dp in datapoints
                ])
                
                # Sort by timestamp
                df = df.sort_values('timestamp')
                
                # Plot the data
                fig = px.line(df, x="timestamp", y="value", 
                             title=f"{selected_metric} over time",
                             labels={"value": f"{selected_metric} ({detailed_data.get('unit', '')})", "timestamp": "Time"})
                st.plotly_chart(fig, use_container_width=True)
                
                # Statistics
                st.subheader("Statistics")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Average", f"{df['value'].mean():.2f}")
                with col2:
                    st.metric("Maximum", f"{df['value'].max():.2f}")
                with col3:
                    st.metric("Minimum", f"{df['value'].min():.2f}")
                with col4:
                    st.metric("Current", f"{df['value'].iloc[-1]:.2f}")

            # Show raw data
            if st.checkbox("Show raw data"):
                if is_cumulative_metric(selected_metric) and 'rate_datapoints' in locals():
                    st.subheader("Rate Data")
                    st.dataframe(df)
                    st.subheader("Cumulative Data")
                    st.dataframe(cumulative_df)
                else:
                    st.dataframe(df)
        else:
            st.warning(f"No data available for {selected_metric}")
    
    with tab3:
        st.header("🤖 AI-Powered Metrics Analysis")
        
        if not app.nim_api_key:
            st.warning("⚠️ NVIDIA NIM API key not configured. Please add your API key in the sidebar.")
            st.info("You can get an API key from NVIDIA's developer portal.")
            return
        
        if selected_instance_info and selected_instance_info['lifecycle_state'] != 'RUNNING':
            st.warning(f"Instance is {selected_instance_info['lifecycle_state']} - metrics not available for AI analysis")
            return
        
        # Get current metrics for context
        with st.spinner("Loading current metrics for AI analysis..."):
            current_metrics = app.get_all_metrics_data(selected_instance_id, selected_compartment_id, 1)
        
        if current_metrics:
            # Prepare context for AI
            context_parts = []
            context_parts.append(f"Instance: {selected_instance_info['display_name']}")
            context_parts.append(f"Shape: {selected_instance_info['shape']}")
            context_parts.append(f"Availability Domain: {selected_instance_info['availability_domain']}")
            
            metrics = current_metrics.get("metrics", {})
            
            for metric_name, metric_data in metrics.items():
                if metric_data.get("datapoints"):
                    if is_cumulative_metric(metric_name):
                        # For IOPS metrics, show rate instead of cumulative
                        rate = calculate_iops_rate(metric_data.get("datapoints", []))
                        if rate is not None:
                            context_parts.append(f"{metric_name}: {rate:.2f} ops/sec")
                        else:
                            context_parts.append(f"{metric_name}: No rate data available")
                    else:
                        latest_value = metric_data["datapoints"][-1].get("value")
                        unit = metric_data.get("unit", "")
                        context_parts.append(f"{metric_name}: {latest_value:.2f} {unit}")
                else:
                    context_parts.append(f"{metric_name}: No data available")
            
            context = "\n".join(context_parts)
            
            # Display current metrics context
            with st.expander("📊 Current Metrics Context"):
                st.text(context)
            
            # AI Query Interface
            st.subheader("Ask the AI Assistant")
            
            # Predefined questions
            st.write("**Quick Questions:**")
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("🔍 Analyze current performance"):
                    query = "Analyze the current performance metrics of this instance. What insights can you provide?"
                    with st.spinner("AI is analyzing..."):
                        response = app.query_nvidia_nim(query, context)
                        st.write("**AI Analysis:**")
                        st.write(response)
                
                if st.button("⚠️ Identify potential issues"):
                    query = "Based on the current metrics, are there any potential performance issues or concerns I should be aware of?"
                    with st.spinner("AI is analyzing..."):
                        response = app.query_nvidia_nim(query, context)
                        st.write("**AI Analysis:**")
                        st.write(response)
            
            with col2:
                if st.button("📈 Optimization recommendations"):
                    query = "What optimization recommendations do you have based on these metrics?"
                    with st.spinner("AI is analyzing..."):
                        response = app.query_nvidia_nim(query, context)
                        st.write("**AI Analysis:**")
                        st.write(response)
                
                if st.button("🎯 Resource scaling advice"):
                    query = "Should I consider scaling this instance up or down based on the current metrics?"
                    with st.spinner("AI is analyzing..."):
                        response = app.query_nvidia_nim(query, context)
                        st.write("**AI Analysis:**")
                        st.write(response)
            
            # Custom query
            st.subheader("Custom Query")
            user_query = st.text_area("Ask a specific question about your OCI metrics:", 
                                    placeholder="e.g., Why is my CPU utilization high? What could be causing memory issues?")
            
            if st.button("🚀 Ask AI") and user_query:
                with st.spinner("AI is thinking..."):
                    response = app.query_nvidia_nim(user_query, context)
                    st.write("**AI Response:**")
                    st.write(response)
        else:
            st.error("Unable to load metrics data for AI analysis")
    
    with tab4:
        st.header("🖥️ Instance Information")
        
        if selected_instance_info:
            # Instance details
            st.subheader("Instance Details")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**Display Name:** {selected_instance_info['display_name']}")
                st.write(f"**Instance ID:** {selected_instance_info['id']}")
                st.write(f"**Lifecycle State:** {selected_instance_info['lifecycle_state']}")
                st.write(f"**Shape:** {selected_instance_info['shape']}")
            
            with col2:
                st.write(f"**Availability Domain:** {selected_instance_info['availability_domain']}")
                st.write(f"**Compartment ID:** {selected_instance_info['compartment_id']}")
                if selected_instance_info['time_created']:
                    created_time = datetime.datetime.fromisoformat(selected_instance_info['time_created'].replace('Z', '+00:00'))
                    st.write(f"**Created:** {created_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            
            # Show all instances in compartment
            st.subheader("All Instances in Selected Compartment")
            
            # Create a DataFrame for better display
            instances_df = pd.DataFrame([
                {
                    "Display Name": inst['display_name'],
                    "State": inst['lifecycle_state'],
                    "Shape": inst['shape'],
                    "Availability Domain": inst['availability_domain'],
                    "Instance ID": inst['id'][:20] + "..."  # Truncate for display
                }
                for inst in instances
            ])
            
            # Color code by state
            def highlight_state(val):
                if val == 'RUNNING':
                    return 'background-color: #d4edda'  # Light green
                elif val == 'STOPPED':
                    return 'background-color: #f8d7da'  # Light red
                else:
                    return 'background-color: #fff3cd'  # Light yellow
            
            styled_df = instances_df.style.applymap(highlight_state, subset=['State'])
            st.dataframe(styled_df, use_container_width=True)
            
            # Compartment information
            st.subheader("Compartment Information")
            st.write(f"**Selected Compartment ID:** {selected_compartment_id}")
            
            # Show available metrics with their types
            st.subheader("Available Metrics")
            available_metrics = app.get_available_metrics()
            if available_metrics:
                st.write("**Standard Metrics (Gauge):**")
                for metric in available_metrics:
                    if not is_cumulative_metric(metric):
                        st.write(f"• {metric} - Real-time value")
                
                st.write("**Cumulative Metrics (Counter):**")
                for metric in available_metrics:
                    if is_cumulative_metric(metric):
                        st.write(f"• {metric} - Cumulative counter (displayed as rate)")
            else:
                st.write("Unable to fetch available metrics")
                
            # Metrics explanation
            with st.expander("📖 Metrics Explanation"):
                st.markdown("""
                **Metric Types:**
                
                **Gauge Metrics** (Real-time values):
                - **CpuUtilization**: Current CPU usage percentage
                - **MemoryUtilization**: Current memory usage percentage  
                - **LoadAverage**: Current system load average
                
                **Counter Metrics** (Cumulative totals):
                - **DiskIopsRead**: Total disk read operations since instance start
                - **DiskIopsWritten**: Total disk write operations since instance start
                
                **Note**: Counter metrics are automatically converted to rates (operations per second) 
                for meaningful real-time monitoring. The dashboard shows both current rates and 
                cumulative totals where applicable.
                
                **Data Collection**:
                - Metrics are collected every minute by the OCI Compute Agent
                - Historical data is available for analysis and trending
                - Rates are calculated from consecutive data points
                """)
        else:
            st.error("No instance information available")
    
    # Footer
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center'>
            <p>🔧 Built with Streamlit • ☁️ Oracle Cloud Infrastructure • 🤖 NVIDIA NIM</p>
            <p><small>Metrics updated every minute • IOPS shown as rates for real-time monitoring</small></p>
        </div>
        """, 
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
