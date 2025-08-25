import kopf
import logging
import kubernetes
import dotenv
import os
import base64
from kubernetes.client.models import RbacV1Subject

dotenv.load_dotenv()


def ensure_api_secrets(namespace, logger):
    """Create API key secrets if they don't exist"""
    core_v1_api = kubernetes.client.CoreV1Api()
    
    # Get API keys from environment
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if not anthropic_key or not openai_key:
        logger.error("ANTHROPIC_API_KEY or OPENAI_API_KEY is not set")
        print(f"ANTHROPIC_API_KEY: {anthropic_key[:10]}")
        print(f"OPENAI_API_KEY: {openai_key[:10]}")
        return
    
    if anthropic_key:
        secret_data = {"ANTHROPIC_API_KEY": base64.b64encode(anthropic_key.encode()).decode()}
        secret = kubernetes.client.V1Secret(
            metadata=kubernetes.client.V1ObjectMeta(name="anthropic-api-key"),
            data=secret_data,
            type="Opaque"
        )
        try:
            core_v1_api.create_namespaced_secret(namespace=namespace, body=secret)
            logger.info(f"Created anthropic-api-key secret in namespace {namespace}")
        except kubernetes.client.exceptions.ApiException as e:
            if e.status == 409:
                logger.info(f"anthropic-api-key secret already exists in namespace {namespace}")
            else:
                raise
    
    if openai_key:
        secret_data = {"OPENAI_API_KEY": base64.b64encode(openai_key.encode()).decode()}
        secret = kubernetes.client.V1Secret(
            metadata=kubernetes.client.V1ObjectMeta(name="openai-api-key"),
            data=secret_data,
            type="Opaque"
        )
        try:
            core_v1_api.create_namespaced_secret(namespace=namespace, body=secret)
            logger.info(f"Created openai-api-key secret in namespace {namespace}")
        except kubernetes.client.exceptions.ApiException as e:
            if e.status == 409:
                logger.info(f"openai-api-key secret already exists in namespace {namespace}")
            else:
                raise


@kopf.on.create("kopf.dev.claud-code", "v1", "claud-code")
def create_claud_code_fn(body, name, namespace, logger, **kwargs):
    logging.info(f"A handler is called with body: {body}")
    metadata_name = body["metadata"]["name"]
    agent_namespace = metadata_name  # Use agent name as namespace
    logger.info(f"creating claud-code agent in namespace: {agent_namespace}")
    metadata_system_prompt = body["system_prompt"]
    mcp_config = body.get("mcp_config", {})
    # Create namespace if it doesn't exist
    core_v1_api = kubernetes.client.CoreV1Api()
    rbac_v1_api = kubernetes.client.RbacAuthorizationV1Api()

    try:
        agent_ns = kubernetes.client.V1Namespace(
            metadata=kubernetes.client.V1ObjectMeta(name=agent_namespace)
        )
        core_v1_api.create_namespace(body=agent_ns)
        logger.info(f"created namespace: {agent_namespace}")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:  # AlreadyExists
            raise
        logger.info(f"namespace {agent_namespace} already exists")
    
    # Ensure API secrets exist in the agent namespace
    ensure_api_secrets(agent_namespace, logger)

    # Create ServiceAccount for the agent
    service_account = kubernetes.client.V1ServiceAccount(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{metadata_name}-agent-sa", namespace=agent_namespace
        )
    )
    try:
        core_v1_api.create_namespaced_service_account(
            namespace=agent_namespace, body=service_account
        )
        logger.info(f"created service account: {metadata_name}-agent-sa")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"service account {metadata_name}-agent-sa already exists")

    # Create Role with permissions to create services, deployments, and access data PV
    role = kubernetes.client.V1Role(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{metadata_name}-agent-role", namespace=agent_namespace
        ),
        rules=[
            kubernetes.client.V1PolicyRule(
                api_groups=[""],
                resources=["services"],
                verbs=["get", "list", "watch", "create", "update", "patch", "delete"],
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=[""],
                resources=["configmaps"],
                verbs=["get", "list", "watch", "create", "update", "patch", "delete"],
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=["networking.k8s.io"],
                resources=["ingresses"],
                verbs=["get", "list", "watch", "create", "update", "patch", "delete"],
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=["apps"],
                resources=["deployments"],
                verbs=["get", "list", "watch", "create", "update", "patch", "delete"],
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=[""],
                resources=["persistentvolumeclaims"],
                resource_names=[f"{metadata_name}-data"],
                verbs=["get", "list", "watch"],
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=[""],
                resources=["pods"],
                verbs=["get", "list", "watch", "create", "update", "patch", "delete"],
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=["batch"],
                resources=["jobs"],
                verbs=["get", "list", "watch", "create", "update", "patch", "delete"],
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=[""], resources=["*"], verbs=["get", "list", "watch"]
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=["apps"], resources=["*"], verbs=["get", "list", "watch"]
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=["batch"], resources=["*"], verbs=["get", "list", "watch"]
            ),
        ],
    )
    try:
        rbac_v1_api.create_namespaced_role(namespace=agent_namespace, body=role)
        logger.info(f"created role: {metadata_name}-agent-role")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"role {metadata_name}-agent-role already exists")

    # Create RoleBinding
    role_binding = kubernetes.client.V1RoleBinding(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{metadata_name}-agent-binding", namespace=agent_namespace
        ),
        role_ref=kubernetes.client.V1RoleRef(
            api_group="rbac.authorization.k8s.io",
            kind="Role",
            name=f"{metadata_name}-agent-role",
        ),
        subjects=[
            RbacV1Subject(
                kind="ServiceAccount",
                name=f"{metadata_name}-agent-sa",
                namespace=agent_namespace,
            )
        ],
    )
    try:
        rbac_v1_api.create_namespaced_role_binding(
            namespace=agent_namespace, body=role_binding
        )
        logger.info(f"created role binding: {metadata_name}-agent-binding")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"role binding {metadata_name}-agent-binding already exists")
    # create a deployment for wholelottahoopla/webagent:latest
    # with metadata dir pvc
    # and a data dir pvc
    # and create a nginx deployment to serve the data dir
    # also create a service for webagent
    # create PVCs first
    metadata_pvc = kubernetes.client.V1PersistentVolumeClaim(
        metadata=kubernetes.client.V1ObjectMeta(name=f"{metadata_name}-metadata"),
        spec=kubernetes.client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=kubernetes.client.V1ResourceRequirements(
                requests={"storage": "1Gi"}
            ),
        ),
    )
    data_pvc = kubernetes.client.V1PersistentVolumeClaim(
        metadata=kubernetes.client.V1ObjectMeta(name=f"{metadata_name}-data"),
        spec=kubernetes.client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=kubernetes.client.V1ResourceRequirements(
                requests={"storage": "1Gi"}
            ),
        ),
    )
    try:
        core_v1_api.create_namespaced_persistent_volume_claim(
            body=metadata_pvc, namespace=agent_namespace
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
    try:
        core_v1_api.create_namespaced_persistent_volume_claim(
            body=data_pvc, namespace=agent_namespace
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
    logger.info("created PVCs")
    
    # Create MCP config ConfigMap
    logger.info("creating mcp config configmap")
    import json
    mcp_config_name = f"{metadata_name}-mcp-config"
    mcp_config_json = json.dumps(mcp_config, indent=2)
    mcp_configmap = kubernetes.client.V1ConfigMap(
        metadata=kubernetes.client.V1ObjectMeta(name=mcp_config_name),
        data={"mcp.json": mcp_config_json},
    )
    try:
        core_v1_api.create_namespaced_config_map(
            namespace=agent_namespace, body=mcp_configmap
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 409:  # AlreadyExists
            core_v1_api.replace_namespaced_config_map(
                name=mcp_config_name, namespace=agent_namespace, body=mcp_configmap
            )
        else:
            raise
    logger.info("created mcp config configmap")
    deployment = kubernetes.client.V1Deployment(
        metadata=kubernetes.client.V1ObjectMeta(name=metadata_name),
        spec=kubernetes.client.V1DeploymentSpec(
            replicas=1,
            selector=kubernetes.client.V1LabelSelector(
                match_labels={"app": metadata_name}
            ),
            template=kubernetes.client.V1PodTemplateSpec(
                metadata=kubernetes.client.V1ObjectMeta(labels={"app": metadata_name}),
                spec=kubernetes.client.V1PodSpec(
                    service_account_name=f"{metadata_name}-agent-sa",
                    containers=[
                        kubernetes.client.V1Container(
                            name=metadata_name,
                            image="wholelottahoopla/webagent:latest",
                            image_pull_policy="Always",
                            args=[
                                "--port",
                                "8081",
                                "--working-dir",
                                "/data/output",
                                "--metadata-dir",
                                "/data/metadata",
                                "--system-prompt",
                                metadata_system_prompt,
                                "--mcp",
                                "/config/mcp.json",
                            ],
                            env=[
                                kubernetes.client.V1EnvVar(
                                    name="ANTHROPIC_API_KEY",
                                    value_from=kubernetes.client.V1EnvVarSource(
                                        secret_key_ref=kubernetes.client.V1SecretKeySelector(
                                            name="anthropic-api-key",
                                            key="ANTHROPIC_API_KEY",
                                        )
                                    ),
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="OPENAI_API_KEY",
                                    value_from=kubernetes.client.V1EnvVarSource(
                                        secret_key_ref=kubernetes.client.V1SecretKeySelector(
                                            name="openai-api-key", key="OPENAI_API_KEY"
                                        )
                                    ),
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="MPLCONFIGDIR",
                                    value="/tmp/matplotlib"
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="TMPDIR",
                                    value="/tmp"
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="HOME",
                                    value="/data/output"
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="XDG_CONFIG_HOME",
                                    value="/data/output/.config"
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="XDG_DATA_HOME",
                                    value="/data/output/.local/share"
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="XDG_CACHE_HOME",
                                    value="/data/output/.cache"
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="CHROME_USER_DATA_DIR",
                                    value="/data/output/.config/google-chrome"
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="CHROME_CRASH_PIPE",
                                    value="/data/output/.config/google-chrome/crash-pipe"
                                ),
                            ],
                            volume_mounts=[
                                kubernetes.client.V1VolumeMount(
                                    name=f"{metadata_name}-data",
                                    mount_path="/data/output",
                                ),
                                kubernetes.client.V1VolumeMount(
                                    name=f"{metadata_name}-metadata",
                                    mount_path="/data/metadata",
                                ),
                                kubernetes.client.V1VolumeMount(
                                    name=f"{mcp_config_name}",
                                    mount_path="/config/mcp.json",
                                    sub_path="mcp.json",
                                ),
                                kubernetes.client.V1VolumeMount(
                                    name="tmp-volume",
                                    mount_path="/tmp",
                                ),
                            ],
                            ports=[
                                kubernetes.client.V1ContainerPort(
                                    name="http", container_port=8081
                                )
                            ],
                        ),
                        kubernetes.client.V1Container(
                            name=f"{metadata_name}-code-server",
                            image="bencdr/code-server-deploy-container:latest",
                            image_pull_policy="Always",
                            env=[
                                kubernetes.client.V1EnvVar(
                                    name="PASSWORD", value="12345"
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="DOCKER_USER", value="coder"
                                ),
                            ],
                            volume_mounts=[
                                kubernetes.client.V1VolumeMount(
                                    name=f"{metadata_name}-data",
                                    mount_path="/home/coder/project",
                                )
                            ],
                            ports=[
                                kubernetes.client.V1ContainerPort(
                                    name="code-server", container_port=8080
                                )
                            ],
                        ),
                    ],
                    volumes=[
                        kubernetes.client.V1Volume(
                            name=f"{metadata_name}-data",
                            persistent_volume_claim=kubernetes.client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=f"{metadata_name}-data"
                            ),
                        ),
                        kubernetes.client.V1Volume(
                            name=f"{metadata_name}-metadata",
                            persistent_volume_claim=kubernetes.client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=f"{metadata_name}-metadata"
                            ),
                        ),
                        kubernetes.client.V1Volume(
                            name=f"{mcp_config_name}",
                            config_map=kubernetes.client.V1ConfigMapVolumeSource(
                                name=mcp_config_name
                            ),
                        ),
                        kubernetes.client.V1Volume(
                            name="tmp-volume",
                            ephemeral=kubernetes.client.V1EphemeralVolumeSource(
                                volume_claim_template=kubernetes.client.V1PersistentVolumeClaimTemplate(
                                    spec=kubernetes.client.V1PersistentVolumeClaimSpec(
                                        access_modes=["ReadWriteOnce"],
                                        resources=kubernetes.client.V1ResourceRequirements(
                                            requests={"storage": "1Gi"}
                                        ),
                                    )
                                )
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )
    try:
        kubernetes.client.AppsV1Api().create_namespaced_deployment(
            body=deployment, namespace=agent_namespace
        )
        logger.info("created deployment")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"deployment {metadata_name} already exists")
    logger.info("creating nginx configmap")
    nginx_conf = f"""
events {{}}
http {{
  server {{
    listen 80;
    root /data/output;
    index index.html;
    autoindex on;
  }}
}}
"""
    configmap_name = f"{metadata_name}-nginx-config"
    nginx_configmap = kubernetes.client.V1ConfigMap(
        metadata=kubernetes.client.V1ObjectMeta(name=configmap_name),
        data={"nginx.conf": nginx_conf},
    )
    try:
        core_v1_api.create_namespaced_config_map(
            namespace=agent_namespace, body=nginx_configmap
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 409:  # AlreadyExists
            core_v1_api.replace_namespaced_config_map(
                name=configmap_name, namespace=agent_namespace, body=nginx_configmap
            )
        else:
            raise
    logger.info("created nginx configmap")
    
    logger.info("creating nginx deployment")
    nginx_name = f"{metadata_name}-nginx"
    nginx_deployment = kubernetes.client.V1Deployment(
        metadata=kubernetes.client.V1ObjectMeta(name=nginx_name),
        spec=kubernetes.client.V1DeploymentSpec(
            replicas=1,
            selector=kubernetes.client.V1LabelSelector(
                match_labels={"app": nginx_name}
            ),
            template=kubernetes.client.V1PodTemplateSpec(
                metadata=kubernetes.client.V1ObjectMeta(labels={"app": nginx_name}),
                spec=kubernetes.client.V1PodSpec(
                    containers=[
                        kubernetes.client.V1Container(
                            name=nginx_name,
                            image="nginx:latest",
                            volume_mounts=[
                                kubernetes.client.V1VolumeMount(
                                    name=f"{metadata_name}-data",
                                    mount_path="/data/output",
                                ),
                                kubernetes.client.V1VolumeMount(
                                    name=f"{configmap_name}",
                                    mount_path="/etc/nginx/nginx.conf",
                                    sub_path="nginx.conf",
                                ),
                            ],
                        )
                    ],
                    volumes=[
                        kubernetes.client.V1Volume(
                            name=f"{metadata_name}-data",
                            persistent_volume_claim=kubernetes.client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=f"{metadata_name}-data"
                            ),
                        ),
                        kubernetes.client.V1Volume(
                            name=f"{configmap_name}",
                            config_map=kubernetes.client.V1ConfigMapVolumeSource(
                                name=configmap_name
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )
    try:
        kubernetes.client.AppsV1Api().create_namespaced_deployment(
            body=nginx_deployment, namespace=agent_namespace
        )
        logger.info("created nginx deployment")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"nginx deployment {nginx_name} already exists")

    # Create services for the deployments
    logger.info("creating services")
    
    # Service for the main deployment (port 8080 and 8081)
    main_service = kubernetes.client.V1Service(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{metadata_name}-service",
            namespace=agent_namespace
        ),
        spec=kubernetes.client.V1ServiceSpec(
            selector={"app": metadata_name},
            ports=[
                kubernetes.client.V1ServicePort(
                    name="code-server",
                    port=8080,
                    target_port=8080,
                    protocol="TCP"
                ),
                kubernetes.client.V1ServicePort(
                    name="http",
                    port=8081,
                    target_port=8081,
                    protocol="TCP"
                )
            ]
        )
    )
    
    # Service for nginx deployment (port 80)
    nginx_service = kubernetes.client.V1Service(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{nginx_name}-service",
            namespace=agent_namespace
        ),
        spec=kubernetes.client.V1ServiceSpec(
            selector={"app": nginx_name},
            ports=[
                kubernetes.client.V1ServicePort(
                    name="http",
                    port=80,
                    target_port=80,
                    protocol="TCP"
                )
            ]
        )
    )
    
    try:
        core_v1_api.create_namespaced_service(
            namespace=agent_namespace, body=main_service
        )
        logger.info(f"created main service: {metadata_name}-service")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"main service {metadata_name}-service already exists")
    
    try:
        core_v1_api.create_namespaced_service(
            namespace=agent_namespace, body=nginx_service
        )
        logger.info(f"created nginx service: {nginx_name}-service")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"nginx service {nginx_name}-service already exists")

    # Create Tailscale ingresses
    logger.info("creating Tailscale ingresses")
    
    # Ingress for code-server (port 8080)
    code_server_ingress = kubernetes.client.V1Ingress(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{metadata_name}-code-server-ingress",
            namespace=agent_namespace,
        ),
        spec=kubernetes.client.V1IngressSpec(
            ingress_class_name="tailscale",
            default_backend=kubernetes.client.V1IngressBackend(
                service=kubernetes.client.V1IngressServiceBackend(
                    name=f"{metadata_name}-service",
                    port=kubernetes.client.V1ServiceBackendPort(
                        number=8080
                    )
                )
            ),
            tls=[
                kubernetes.client.V1IngressTLS(
                    hosts=[f"{metadata_name}-code-server"]
                )
            ]
        )
    )
    
    # Ingress for http service (port 8081)
    http_ingress = kubernetes.client.V1Ingress(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{metadata_name}-http-ingress",
            namespace=agent_namespace,

        ),
        spec=kubernetes.client.V1IngressSpec(
            ingress_class_name="tailscale",
            default_backend=kubernetes.client.V1IngressBackend(
                service=kubernetes.client.V1IngressServiceBackend(
                    name=f"{metadata_name}-service",
                    port=kubernetes.client.V1ServiceBackendPort(
                        number=8081
                    )
                )
            ),
            tls=[
                kubernetes.client.V1IngressTLS(
                    hosts=[f"{metadata_name}-http"]
                )
            ]
        )
    )
    
    # Ingress for nginx (port 80)
    nginx_ingress = kubernetes.client.V1Ingress(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{nginx_name}-ingress",
            namespace=agent_namespace,
        ),
        spec=kubernetes.client.V1IngressSpec(
            ingress_class_name="tailscale",
            default_backend=kubernetes.client.V1IngressBackend(
                service=kubernetes.client.V1IngressServiceBackend(
                    name=f"{nginx_name}-service",
                    port=kubernetes.client.V1ServiceBackendPort(
                        number=80
                    )
                )
            ),
            tls=[
                kubernetes.client.V1IngressTLS(
                    hosts=[f"{metadata_name}-nginx"]
                )
            ]
        )
    )
    
    networking_v1_api = kubernetes.client.NetworkingV1Api()
    
    try:
        networking_v1_api.create_namespaced_ingress(
            namespace=agent_namespace, body=code_server_ingress
        )
        logger.info(f"created code-server ingress: {metadata_name}-code-server-ingress")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"code-server ingress {metadata_name}-code-server-ingress already exists")
    
    try:
        networking_v1_api.create_namespaced_ingress(
            namespace=agent_namespace, body=http_ingress
        )
        logger.info(f"created http ingress: {metadata_name}-http-ingress")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"http ingress {metadata_name}-http-ingress already exists")
    
    try:
        networking_v1_api.create_namespaced_ingress(
            namespace=agent_namespace, body=nginx_ingress
        )
        logger.info(f"created nginx ingress: {nginx_name}-ingress")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"nginx ingress {nginx_name}-ingress already exists")


# delete the deployment and service for the claud-code and nginx and remove the pvc
@kopf.on.delete("kopf.dev.claud-code", "v1", "claud-code")
def delete_claud_code_fn(body, **kwargs):
    from kubernetes.client.exceptions import ApiException

    logging.info(f"A handler is called with body: {body}")
    metadata_name = body["metadata"]["name"]
    agent_namespace = metadata_name  # Use agent name as namespace
    logger = logging.getLogger(__name__)
    logger.info(f"deleting claud-code agent from namespace: {agent_namespace}")
    try:
        kubernetes.client.AppsV1Api().delete_namespaced_deployment(
            name=metadata_name, namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted deployment")
    logger.info("deleting nginx configmap")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_config_map(
            name=f"{metadata_name}-nginx-config", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx configmap")
    logger.info("deleting nginx deployment")
    try:
        kubernetes.client.AppsV1Api().delete_namespaced_deployment(
            name=f"{metadata_name}-nginx", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx deployment")
    
    # Delete services
    logger.info("deleting services")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_service(
            name=f"{metadata_name}-service", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted main service")
    
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_service(
            name=f"{metadata_name}-nginx-service", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx service")
    
    # Delete ingresses
    logger.info("deleting ingresses")
    networking_v1_api = kubernetes.client.NetworkingV1Api()
    
    try:
        networking_v1_api.delete_namespaced_ingress(
            name=f"{metadata_name}-code-server-ingress", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted code-server ingress")
    
    try:
        networking_v1_api.delete_namespaced_ingress(
            name=f"{metadata_name}-http-ingress", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted http ingress")
    
    try:
        networking_v1_api.delete_namespaced_ingress(
            name=f"{metadata_name}-nginx-ingress", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx ingress")
    
    logger.info("deleting pvc")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_persistent_volume_claim(
            name=f"{metadata_name}-metadata", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted metadata pvc")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_persistent_volume_claim(
            name=f"{metadata_name}-data", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted data pvc")

    # Clean up RBAC resources
    try:
        kubernetes.client.RbacAuthorizationV1Api().delete_namespaced_role_binding(
            name=f"{metadata_name}-agent-binding", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted role binding")

    try:
        kubernetes.client.RbacAuthorizationV1Api().delete_namespaced_role(
            name=f"{metadata_name}-agent-role", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted role")

    try:
        kubernetes.client.CoreV1Api().delete_namespaced_service_account(
            name=f"{metadata_name}-agent-sa", namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted service account")

    # Optionally delete the namespace (uncomment if you want to clean up completely)
    # try:
    #     kubernetes.client.CoreV1Api().delete_namespace(name=agent_namespace)
    # except ApiException as e:
    #     if e.status != 404:
    #         raise
    # logger.info(f"deleted namespace: {agent_namespace}")

    logger.info("deleted claud-code")


@kopf.on.update("kopf.dev.claud-code", "v1", "claud-code")
def update_claud_code_fn(body, name, namespace, logger, diff, **kwargs):
    import kubernetes
    from kubernetes.client.exceptions import ApiException

    metadata_name = body["metadata"]["name"]
    agent_namespace = metadata_name  # Use agent name as namespace
    
    # Track what changes were made
    system_prompt_changed = False
    data_changed = False
    
    # Check what fields changed
    for d in diff:
        if d[1] == ("system_prompt",):
            system_prompt_changed = True
            logger.info(f"system_prompt changed: {d}")
        elif d[1] == ("data",) or (len(d[1]) > 0 and d[1][0] == "data"):
            data_changed = True
            logger.info(f"data field changed: {d}")
    
    if not system_prompt_changed and not data_changed:
        logger.info("No relevant fields changed, skipping update.")
        return

    logger.info(f"Updating claud-code resource {metadata_name} in namespace {agent_namespace}")

    # Handle system_prompt updates
    if system_prompt_changed:
        new_system_prompt = body.get("system_prompt")
        logger.info(f"Updating system prompt for deployment {metadata_name}")

        # Get the current deployment
        apps_v1_api = kubernetes.client.AppsV1Api()
        try:
            deployment = apps_v1_api.read_namespaced_deployment(
                name=metadata_name, namespace=agent_namespace
            )
        except ApiException as e:
            if e.status == 404:
                logger.error(f"Deployment {metadata_name} not found in namespace {agent_namespace}")
                return
            else:
                raise

        # Update the system prompt in the container args
        updated = False
        for container in deployment.spec.template.spec.containers:
            if container.name == metadata_name:
                if container.args is None:
                    container.args = []
                if "--system-prompt" in container.args:
                    idx = container.args.index("--system-prompt")
                    if idx + 1 < len(container.args):
                        container.args[idx + 1] = new_system_prompt
                        updated = True
                else:
                    container.args.extend(["--system-prompt", new_system_prompt])
                    updated = True

        if updated:
            # Patch the deployment with the new args
            try:
                patch_body = {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {"name": metadata_name, "args": container.args}
                                ]
                            }
                        }
                    }
                }
                apps_v1_api.patch_namespaced_deployment(
                    name=metadata_name, namespace=agent_namespace, body=patch_body
                )
                logger.info(f"Successfully updated system prompt for deployment {metadata_name}")
            except ApiException as e:
                logger.error(f"Failed to patch deployment: {e}")
                raise
        else:
            logger.info("No update needed for system prompt in deployment.")

    # Handle data field updates
    if data_changed:
        data_field = body.get("data", {})
        logger.info(f"Updating data field: {data_field}")
        
        # Update API secrets if API keys are in the data field
        if "ANTHROPIC_API_KEY" in data_field or "OPENAI_API_KEY" in data_field:
            logger.info("API keys found in data field, updating secrets")
            try:
                core_v1_api = kubernetes.client.CoreV1Api()
                
                # Update Anthropic API key if present
                if "ANTHROPIC_API_KEY" in data_field:
                    anthropic_key = data_field["ANTHROPIC_API_KEY"]
                    secret_data = {"ANTHROPIC_API_KEY": base64.b64encode(anthropic_key.encode()).decode()}
                    secret = kubernetes.client.V1Secret(
                        metadata=kubernetes.client.V1ObjectMeta(name="anthropic-api-key"),
                        data=secret_data,
                        type="Opaque"
                    )
                    try:
                        core_v1_api.replace_namespaced_secret(
                            name="anthropic-api-key", namespace=agent_namespace, body=secret
                        )
                        logger.info("Updated anthropic-api-key secret")
                    except ApiException as e:
                        if e.status == 404:
                            core_v1_api.create_namespaced_secret(namespace=agent_namespace, body=secret)
                            logger.info("Created anthropic-api-key secret")
                        else:
                            raise
                
                # Update OpenAI API key if present
                if "OPENAI_API_KEY" in data_field:
                    openai_key = data_field["OPENAI_API_KEY"]
                    secret_data = {"OPENAI_API_KEY": base64.b64encode(openai_key.encode()).decode()}
                    secret = kubernetes.client.V1Secret(
                        metadata=kubernetes.client.V1ObjectMeta(name="openai-api-key"),
                        data=secret_data,
                        type="Opaque"
                    )
                    try:
                        core_v1_api.replace_namespaced_secret(
                            name="openai-api-key", namespace=agent_namespace, body=secret
                        )
                        logger.info("Updated openai-api-key secret")
                    except ApiException as e:
                        if e.status == 404:
                            core_v1_api.create_namespaced_secret(namespace=agent_namespace, body=secret)
                            logger.info("Created openai-api-key secret")
                        else:
                            raise
                            
                # Restart deployment to pick up new secrets
                apps_v1_api = kubernetes.client.AppsV1Api()
                try:
                    deployment = apps_v1_api.read_namespaced_deployment(
                        name=metadata_name, namespace=agent_namespace
                    )
                    # Add or update restart annotation to trigger pod restart
                    import datetime
                    if deployment.spec.template.metadata.annotations is None:
                        deployment.spec.template.metadata.annotations = {}
                    deployment.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    
                    apps_v1_api.patch_namespaced_deployment(
                        name=metadata_name, namespace=agent_namespace, body=deployment
                    )
                    logger.info("Restarted deployment to pick up updated secrets")
                except ApiException as e:
                    logger.error(f"Failed to restart deployment: {e}")
                    
            except Exception as e:
                logger.error(f"Failed to update API secrets: {e}")
                raise
        
        # Handle other data field updates
        logger.info(f"Data field updated with: {list(data_field.keys())}")

    logger.info(f"Update handler completed for {metadata_name}")
