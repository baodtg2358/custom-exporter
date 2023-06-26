from http.server import BaseHTTPRequestHandler, HTTPServer
from prometheus_client import Gauge, generate_latest, start_http_server
from kubernetes import client
from kubernetes.client import configuration
import json, re, os, logging

logging.basicConfig(level= logging.INFO,format='%(asctime)s - %(levelname)s: %(message)s')

config =  configuration.Configuration()
namespace_spec= os.getenv("NAMESPACE")
host = os.getenv("HOST", "https://kubernetes.default.svc")

config =  configuration.Configuration()
config.host = host
with open("/var/run/secrets/kubernetes.io/serviceaccount/token", "r") as token_file:
    token = token_file.read().strip()
config.api_key = {"authorization": f"Bearer {token}"}
config.ssl_ca_cert = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
api_client = client.ApiClient(configuration=config)

api_instance = client.CustomObjectsApi(api_client=api_client)

api_group= "metrics.k8s.io"
api_version= "v1beta1"
resource_plural = "pods"

cpu_usage = Gauge('pod_cpu_usage', 'CPU usage of a pod', ['pod_name', 'namespace'])
memory_usage = Gauge('pod_memory_usage', 'Memory usage of a pod', ['pod_name', 'namespace'])


if namespace_spec is not None and host is not None:
    def get_metrics():
        api_response = api_instance.list_namespaced_custom_object(
            group=api_group,
            version=api_version,
            namespace=namespace_spec,
            plural=resource_plural
        )
        json_data = json.dumps(api_response)
        data = json.loads(json_data)
        logging.info(f"Metrics: {api_response}")
        # Extract metrics from the JSON data
        for item in data['items']:
            pod_name = item['metadata']['name']
            namespace = item['metadata']['namespace']
            cpu = item['containers'][0]['usage']['cpu']
            memory = item['containers'][0]['usage']['memory']

            # Convert memory value to bytes
            match = re.match(r'(\d+)([KMG]i?)', memory)
            if match:
                value, unit = match.groups()
                if unit == 'Ki':
                    memory_bytes = int(value) * 1024
                elif unit == 'Mi':
                    memory_bytes = int(value) * 1024 * 1024
                elif unit == 'Gi':
                    memory_bytes = int(value) * 1024 * 1024 * 1024
                else:
                    raise ValueError(f"Invalid memory unit: {unit}")
            else:
                raise ValueError(f"Invalid memory value: {memory}")

            cpu_value = re.sub(r'[^0-9.]', '', cpu)
            cpu_millicores = float(int(cpu_value)/1000000) # 1 millicores = 1000000 nanocores - 1cores = 1000000000 millicores
            cpu_usage.labels(pod_name=pod_name, namespace=namespace).set(cpu_millicores)
            memory_usage.labels(pod_name=pod_name, namespace=namespace).set(memory_bytes)

        logging.info("Metrics retrieved successfully")

    class MetricHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/metrics':
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                get_metrics()
                self.wfile.write(generate_latest())
            else:
                self.send_response(404)
                self.end_headers()

    # Start the Prometheus HTTP server
    start_http_server(8000)

    # Start the custom MetricHandler server
    server_address = ('', 8081)
    httpd = HTTPServer(server_address, MetricHandler)
    logging.info("Server Started!")
    logging.info(f"Starting retrieve metrics from namespace: {namespace_spec}")
    logging.info(f"Starting retrieve metrics from host: {host}")
    httpd.serve_forever()

else: print("Cannot define namespace or host!")