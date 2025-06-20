import asyncio
import json
import logging
from datetime import datetime, timedelta
import argparse
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import oci
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Parse command-line arguments for auth method
parser = argparse.ArgumentParser(description="OCI Metrics Server")
parser.add_argument(
    "--user-principal",
    action="store_true",
    help="Use user principal from OCI config file instead of instance principal (default)."
)
# Use parse_known_args to avoid conflicts with uvicorn arguments
args, _ = parser.parse_known_args()


app = FastAPI(title="OCI Metrics Server", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class OCIMetricsService:
    def __init__(self, use_user_principal: bool = False):
        self.use_user_principal = use_user_principal
        self.setup_oci_clients()
        # Metrics we're interested in
        self.target_metrics = [
            "CpuUtilization",
            "DiskIopsRead", 
            "DiskIopsWritten",
            "LoadAverage",
            "MemoryUtilization"
        ]
    
    def setup_oci_clients(self):
        """Initialize OCI clients based on the chosen authentication method."""
        try:
            if self.use_user_principal:
                logger.info("Initializing OCI clients using user principal (from config file)...")
                self.config = oci.config.from_file()

                # Initialize clients with config from file
                self.compute_client = oci.core.ComputeClient(self.config)
                self.monitoring_client = oci.monitoring.MonitoringClient(self.config)
                self.identity_client = oci.identity.IdentityClient(self.config)

                logger.info("OCI clients initialized successfully using config file.")
                logger.info(f"Tenancy ID: {self.config['tenancy']}")
                logger.info(f"User ID: {self.config['user']}")
                logger.info(f"Region: {self.config['region']}")
            
            else: # Default to instance_principal
                logger.info("Initializing OCI clients using Instance Principals...")
                signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
                self.config = {'region': signer.region, 'tenancy': signer.tenancy_id}

                # Initialize clients with the signer
                self.compute_client = oci.core.ComputeClient({}, signer=signer)
                self.monitoring_client = oci.monitoring.MonitoringClient({}, signer=signer)
                self.identity_client = oci.identity.IdentityClient({}, signer=signer)

                logger.info("OCI clients initialized successfully using Instance Principals.")
                logger.info(f"Tenancy ID: {self.config['tenancy']}")
                logger.info(f"Region: {self.config['region']}")

        except Exception as e:
            auth_method = "user_principal" if self.use_user_principal else "instance_principal"
            logger.error(f"Failed to initialize OCI clients using '{auth_method}': {e}")
            if not self.use_user_principal:
                logger.error("For local development, use the --user-principal flag.")
            else:
                logger.error("Ensure your OCI config file is correctly set up at ~/.oci/config")
            raise
    
    def get_compartments(self, parent_compartment_id: Optional[str] = None) -> List[Dict]:
        """Get list of compartments"""
        try:
            if not parent_compartment_id:
                parent_compartment_id = self.config["tenancy"]
            
            logger.info(f"Getting compartments for parent: {parent_compartment_id}")
            
            compartments = []
            
            # Add root compartment (tenancy)
            if parent_compartment_id == self.config["tenancy"]:
                compartments.append({
                    "id": self.config["tenancy"],
                    "name": "root (tenancy)",
                    "description": "Root tenancy compartment",
                    "lifecycle_state": "ACTIVE"
                })
            
            # Get sub-compartments
            try:
                response = self.identity_client.list_compartments(
                    compartment_id=parent_compartment_id,
                    compartment_id_in_subtree=True,
                    access_level="ACCESSIBLE",
                    lifecycle_state="ACTIVE"
                )
                
                for compartment in response.data:
                    if compartment.lifecycle_state == "ACTIVE":
                        compartments.append({
                            "id": compartment.id,
                            "name": compartment.name,
                            "description": compartment.description or "No description",
                            "lifecycle_state": compartment.lifecycle_state
                        })
                        
            except Exception as e:
                logger.warning(f"Could not list sub-compartments: {e}")
            
            logger.info(f"Found {len(compartments)} compartments")
            return compartments
            
        except Exception as e:
            logger.error(f"Error getting compartments: {e}")
            raise
    
    def get_compute_instances(self, compartment_id: str) -> List[Dict]:
        """Get list of compute instances from a specific compartment"""
        try:
            logger.info(f"Getting instances from compartment: {compartment_id}")
            
            # List instances in the specified compartment
            instances_response = self.compute_client.list_instances(
                compartment_id=compartment_id
            )
            
            instances = instances_response.data
            running_instances = [i for i in instances if i.lifecycle_state == "RUNNING"]
            
            logger.info(f"Found {len(instances)} total instances ({len(running_instances)} running) in compartment")
            
            instance_list = []
            for instance in instances:
                instance_info = {
                    "id": instance.id,
                    "display_name": instance.display_name,
                    "lifecycle_state": instance.lifecycle_state,
                    "availability_domain": instance.availability_domain,
                    "compartment_id": instance.compartment_id,
                    "shape": instance.shape,
                    "time_created": instance.time_created.isoformat() if instance.time_created else None,
                }
                instance_list.append(instance_info)
                
                status_emoji = "✅" if instance.lifecycle_state == "RUNNING" else "⏸️"
                logger.info(f"{status_emoji} Instance: {instance.display_name} - {instance.lifecycle_state}")
            
            return instance_list
            
        except Exception as e:
            logger.error(f"Error getting compute instances: {e}")
            raise
    
    def get_instance_metric_data(self, instance_id: str, metric_name: str, compartment_id: str, hours_back: int = 1) -> Dict:
        """Get metric data for a specific instance and metric"""
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=hours_back)
            
            logger.info(f"Getting {metric_name} for instance {instance_id} in compartment {compartment_id}")
            logger.info(f"Time range: {start_time} to {end_time}")
            
            # Build the metric query
            query = f'{metric_name}[1m]{{resourceId = "{instance_id}"}}.mean()'
            
            summarize_metrics_data_details = oci.monitoring.models.SummarizeMetricsDataDetails(
                namespace="oci_computeagent",
                query=query,
                start_time=start_time,
                end_time=end_time,
                resolution="1m"
            )
            
            # Use the specific compartment ID for the metrics query
            response = self.monitoring_client.summarize_metrics_data(
                compartment_id=compartment_id,  # This is crucial!
                summarize_metrics_data_details=summarize_metrics_data_details
            )
            
            # Process the response
            result = {
                "instance_id": instance_id,
                "metric_name": metric_name,
                "namespace": "oci_computeagent",
                "compartment_id": compartment_id,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "datapoints": []
            }
            
            if response.data:
                for metric_data in response.data:
                    if metric_data.aggregated_datapoints:
                        for datapoint in metric_data.aggregated_datapoints:
                            result["datapoints"].append({
                                "timestamp": datapoint.timestamp.isoformat(),
                                "value": datapoint.value
                            })
                    
                    # Add metadata
                    result["unit"] = getattr(metric_data, 'unit', None)
                    result["resolution"] = getattr(metric_data, 'resolution', None)
            
            logger.info(f"Retrieved {len(result['datapoints'])} datapoints for {metric_name}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting metric data: {e}")
            raise
    
    def get_all_instance_metrics(self, instance_id: str, compartment_id: str, hours_back: int = 1) -> Dict:
        """Get all target metrics for an instance"""
        try:
            all_metrics = {}
            
            for metric_name in self.target_metrics:
                try:
                    metric_data = self.get_instance_metric_data(
                        instance_id, metric_name, compartment_id, hours_back
                    )
                    all_metrics[metric_name] = metric_data
                except Exception as e:
                    logger.warning(f"Failed to get {metric_name} for {instance_id}: {e}")
                    all_metrics[metric_name] = {"error": str(e)}
            
            return {
                "instance_id": instance_id,
                "compartment_id": compartment_id,
                "metrics": all_metrics,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting all metrics: {e}")
            raise

# Initialize the service
oci_service = OCIMetricsService(use_user_principal=args.user_principal)

@app.get("/")
async def root():
    return {"message": "OCI Metrics Server", "version": "1.0.0"}

@app.get("/compartments")
async def get_compartments(parent_compartment_id: Optional[str] = None):
    """Get list of compartments"""
    try:
        compartments = oci_service.get_compartments(parent_compartment_id)
        return {"compartments": compartments}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/instances")
async def get_instances(compartment_id: str):
    """Get list of compute instances in a specific compartment"""
    try:
        instances = oci_service.get_compute_instances(compartment_id)
        return {"instances": instances, "compartment_id": compartment_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/instances/{instance_id}/metrics/{metric_name}")
async def get_instance_metric(instance_id: str, metric_name: str, compartment_id: str, hours_back: int = 1):
    """Get specific metric for an instance"""
    try:
        if metric_name not in oci_service.target_metrics:
            raise HTTPException(status_code=400, detail=f"Invalid metric name. Available: {oci_service.target_metrics}")
        
        metric_data = oci_service.get_instance_metric_data(instance_id, metric_name, compartment_id, hours_back)
        return metric_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/instances/{instance_id}/metrics")
async def get_all_instance_metrics(instance_id: str, compartment_id: str, hours_back: int = 1):
    """Get all metrics for an instance"""
    try:
        all_metrics = oci_service.get_all_instance_metrics(instance_id, compartment_id, hours_back)
        return all_metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
async def get_available_metrics():
    """Get list of available metrics"""
    return {
        "available_metrics": oci_service.target_metrics,
        "namespace": "oci_computeagent"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
