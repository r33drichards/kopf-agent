import kopf
import logging
import kubernetes
import dotenv
from kubernetes.client.models import V1Subject

dotenv.load_dotenv()


@kopf.on.create('kopf.dev.llmrequests', 'v1', 'llmrequests')
def create_fn(body, name, namespace, logger, **kwargs):
    logging.info(f"A handler is called with body: {body}")
    # read the prompt from the body
    prompt = body['prompt']
    metadata_name = body['metadata']['name']
    logger.info("got prompt", prompt)
    logger.info("creating job")
    
    # create a new job instead of a pod
    job = kubernetes.client.V1Job(
        metadata=kubernetes.client.V1ObjectMeta(name=metadata_name, labels={"app": metadata_name}),
        spec=kubernetes.client.V1JobSpec(
            template=kubernetes.client.V1PodTemplateSpec(
                metadata=kubernetes.client.V1ObjectMeta(labels={"app": metadata_name}),
                spec=kubernetes.client.V1PodSpec(
                    containers=[
                        kubernetes.client.V1Container(
                            name=metadata_name,
                            image="wholelottahoopla/bash-agent:latest",
                            image_pull_policy="Always",
                            env=[
                                kubernetes.client.V1EnvVar(
                                    name="ANTHROPIC_API_KEY",
                                    value_from=kubernetes.client.V1EnvVarSource(
                                        secret_key_ref=kubernetes.client.V1SecretKeySelector(
                                            name="anthropic-api-key",
                                            key="ANTHROPIC_API_KEY"
                                        )
                                    )
                                )
                            ],
                            volume_mounts=[
                                kubernetes.client.V1VolumeMount(
                                    name=f"{metadata_name}",
                                    mount_path="/data/output"
                                )
                            ],
                            args=[
                                "--auto-confirm",
                                "--initial-user-input",
                                prompt
                            ]
                        )
                    ],
                    restart_policy="Never",
                    volumes=[
                        kubernetes.client.V1Volume(
                            name=f"{metadata_name}",
                            host_path=kubernetes.client.V1HostPathVolumeSource(
                                path="/data/output"
                            )
                        )
                    ]
                )
            ),
            backoff_limit=0
        )
    )   
    # create the job
    kubernetes.client.BatchV1Api().create_namespaced_job(
        body=job,
        namespace="default"
    )
    logger.info("created job")
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
        data={"nginx.conf": nginx_conf}
    )
    kubernetes.client.CoreV1Api().create_namespaced_config_map(
        namespace="default",
        body=nginx_configmap
    )
    logger.info("created nginx configmap")
    logger.info("creating nginx deployment")
    # serve the pvc with nginx
    nginx_name = f"{metadata_name}-nginx"
    nginx_deployment = kubernetes.client.V1Deployment(
        metadata=kubernetes.client.V1ObjectMeta(name=nginx_name),
        spec=kubernetes.client.V1DeploymentSpec(
            replicas=1,
            selector=kubernetes.client.V1LabelSelector(match_labels={"app": nginx_name}),
            template=kubernetes.client.V1PodTemplateSpec(
                metadata=kubernetes.client.V1ObjectMeta(labels={"app": nginx_name}),
                spec=kubernetes.client.V1PodSpec(
                    containers=[
                        kubernetes.client.V1Container(
                            name=nginx_name,
                            image="nginx:latest",
                            volume_mounts=[
                                kubernetes.client.V1VolumeMount(
                                    name=f"{metadata_name}",
                                    mount_path="/data/output"
                                ),
                                kubernetes.client.V1VolumeMount(
                                    name=f"{configmap_name}",
                                    mount_path="/etc/nginx/nginx.conf",
                                    sub_path="nginx.conf"
                                )
                            ]
                        )
                    ],  
                    volumes=[
                        kubernetes.client.V1Volume(
                            name=f"{metadata_name}",
                            host_path=kubernetes.client.V1HostPathVolumeSource(
                                path="/data/output"
                            )
                        ),
                        kubernetes.client.V1Volume(
                            name=f"{configmap_name}",
                            config_map=kubernetes.client.V1ConfigMapVolumeSource(
                                name=configmap_name
                            )
                        )
                    ]
                )
            )
        )
    )
    # create the deployment 
    kubernetes.client.AppsV1Api().create_namespaced_deployment(
        body=nginx_deployment,
        namespace="default"
    )
    logger.info("created nginx deployment")




# delete the deployment and service
@kopf.on.delete('kopf.dev.llmrequests', 'v1', 'llmrequests')
def delete_fn(body, name, namespace, logger, **kwargs):
    logging.info(f"A handler is called with body: {body}")
    metadata_name = body['metadata']['name']
    logger.info("deleting job")
    try:
        kubernetes.client.BatchV1Api().delete_namespaced_job(
            name=metadata_name,
            namespace="default"
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted job")
    logger.info("deleting nginx configmap")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_config_map(
            name=f"{metadata_name}-nginx-config",
            namespace="default"
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx configmap")
    logger.info("deleting nginx deployment")
    try:
        kubernetes.client.AppsV1Api().delete_namespaced_deployment(
            name=f"{metadata_name}-nginx",
            namespace="default"
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx deployment")


@kopf.on.create('kopf.dev.claud-code', 'v1', 'claud-code')
def create_fn(body, name, namespace, logger, **kwargs):
    logging.info(f"A handler is called with body: {body}")
    metadata_name = body['metadata']['name']
    agent_namespace = metadata_name  # Use agent name as namespace
    logger.info(f"creating claud-code agent in namespace: {agent_namespace}")
    metadata_system_prompt = body['system_prompt']
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
    
    # Create ServiceAccount for the agent
    service_account = kubernetes.client.V1ServiceAccount(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{metadata_name}-agent-sa",
            namespace=agent_namespace
        )
    )
    try:
        core_v1_api.create_namespaced_service_account(
            namespace=agent_namespace,
            body=service_account
        )
        logger.info(f"created service account: {metadata_name}-agent-sa")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"service account {metadata_name}-agent-sa already exists")
    
    # Create Role with permissions to create services and read all resources
    role = kubernetes.client.V1Role(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{metadata_name}-agent-role",
            namespace=agent_namespace
        ),
        rules=[
            kubernetes.client.V1PolicyRule(
                api_groups=[""],
                resources=["services"],
                verbs=["get", "list", "watch", "create", "update", "patch", "delete"]
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=[""],
                resources=["*"],
                verbs=["get", "list", "watch"]
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=["apps"],
                resources=["*"],
                verbs=["get", "list", "watch"]
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=["batch"],
                resources=["*"],
                verbs=["get", "list", "watch"]
            )
        ]
    )
    try:
        rbac_v1_api.create_namespaced_role(
            namespace=agent_namespace,
            body=role
        )
        logger.info(f"created role: {metadata_name}-agent-role")
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
        logger.info(f"role {metadata_name}-agent-role already exists")
    
    # Create RoleBinding
    role_binding = kubernetes.client.V1RoleBinding(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{metadata_name}-agent-binding",
            namespace=agent_namespace
        ),
        role_ref=kubernetes.client.V1RoleRef(
            api_group="rbac.authorization.k8s.io",
            kind="Role",
            name=f"{metadata_name}-agent-role"
        ),
        subjects=[
            V1Subject(
                kind="ServiceAccount",
                name=f"{metadata_name}-agent-sa",
                namespace=agent_namespace
            )
        ]
    )
    try:
        rbac_v1_api.create_namespaced_role_binding(
            namespace=agent_namespace,
            body=role_binding
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
            resources=kubernetes.client.V1ResourceRequirements(requests={"storage": "1Gi"})
        )
    )
    data_pvc = kubernetes.client.V1PersistentVolumeClaim(
        metadata=kubernetes.client.V1ObjectMeta(name=f"{metadata_name}-data"),
        spec=kubernetes.client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=kubernetes.client.V1ResourceRequirements(requests={"storage": "1Gi"})
        )
    )
    try:
        core_v1_api.create_namespaced_persistent_volume_claim(
            body=metadata_pvc,
            namespace=agent_namespace
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
    try:
        core_v1_api.create_namespaced_persistent_volume_claim(
            body=data_pvc,
            namespace=agent_namespace
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
    logger.info("created PVCs")
    deployment = kubernetes.client.V1Deployment(
        metadata=kubernetes.client.V1ObjectMeta(name=metadata_name),
        spec=kubernetes.client.V1DeploymentSpec(
            replicas=1,
            selector=kubernetes.client.V1LabelSelector(match_labels={"app": metadata_name}),
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
                                metadata_system_prompt
                            ],
                            env=[
                                kubernetes.client.V1EnvVar(
                                    name="ANTHROPIC_API_KEY",
                                    value_from=kubernetes.client.V1EnvVarSource(
                                        secret_key_ref=kubernetes.client.V1SecretKeySelector(
                                            name="anthropic-api-key",
                                            key="ANTHROPIC_API_KEY"
                                        )
                                    )
                                )
                            ],
                            volume_mounts=[
                                kubernetes.client.V1VolumeMount(
                                    name=f"{metadata_name}-data",
                                    mount_path="/data/output"
                                ),
                                kubernetes.client.V1VolumeMount(
                                    name=f"{metadata_name}-metadata",
                                    mount_path="/data/metadata"
                                )
                            ],
                            ports=[
                                kubernetes.client.V1ContainerPort(
                                    name="http",
                                    container_port=8081
                                )
                            ]
                        ),
                        kubernetes.client.V1Container(
                            name=f"{metadata_name}-code-server",
                            image="bencdr/code-server-deploy-container:latest",
                            image_pull_policy="Always",
                            env=[
                                kubernetes.client.V1EnvVar(
                                    name="PASSWORD",
                                    value="12345"
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="DOCKER_USER",
                                    value="coder"
                                ),
                            ],
                            volume_mounts=[
                                kubernetes.client.V1VolumeMount(
                                    name=f"{metadata_name}-data",
                                    mount_path="/home/coder/project"
                                )
                            ],
                            ports=[
                                kubernetes.client.V1ContainerPort(
                                    name="code-server",
                                    container_port=8080
                                )
                            ]
                        )
                    ],
                    volumes=[
                        kubernetes.client.V1Volume(
                            name=f"{metadata_name}-data",
                            persistent_volume_claim=kubernetes.client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=f"{metadata_name}-data"
                            )
                        ),
                        kubernetes.client.V1Volume(
                            name=f"{metadata_name}-metadata",
                            persistent_volume_claim=kubernetes.client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=f"{metadata_name}-metadata"
                            )
                        )
                    ]
                )
            )
        )
    )
    kubernetes.client.AppsV1Api().create_namespaced_deployment(
        body=deployment,
        namespace=agent_namespace
    )
    logger.info("created deployment")
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
        data={"nginx.conf": nginx_conf}
    )
    try:
        core_v1_api.create_namespaced_config_map(
            namespace=agent_namespace,
            body=nginx_configmap
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 409:  # AlreadyExists
            core_v1_api.replace_namespaced_config_map(
                name=configmap_name,
                namespace=agent_namespace,
                body=nginx_configmap
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
            selector=kubernetes.client.V1LabelSelector(match_labels={"app": nginx_name}),
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
                                    mount_path="/data/output"
                                ),
                                kubernetes.client.V1VolumeMount(
                                    name=f"{configmap_name}",
                                    mount_path="/etc/nginx/nginx.conf",
                                    sub_path="nginx.conf"
                                )
                            ]
                        )
                    ],
                    volumes=[
                        kubernetes.client.V1Volume(
                            name=f"{metadata_name}-data",
                            persistent_volume_claim=kubernetes.client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=f"{metadata_name}-data"
                            )
                        ),
                        kubernetes.client.V1Volume(
                            name=f"{configmap_name}",
                            config_map=kubernetes.client.V1ConfigMapVolumeSource(
                                name=configmap_name
                            )
                        )
                    ]
                )
            )
        )
    )
    kubernetes.client.AppsV1Api().create_namespaced_deployment(
        body=nginx_deployment,
        namespace=agent_namespace
    )
    logger.info("created nginx deployment")




# delete the deployment and service for the claud-code and nginx and remove the pvc
@kopf.on.delete('kopf.dev.claud-code', 'v1', 'claud-code')
def delete_claud_code_fn(body, **kwargs):
    from kubernetes.client.exceptions import ApiException
    logging.info(f"A handler is called with body: {body}")
    metadata_name = body['metadata']['name']
    agent_namespace = metadata_name  # Use agent name as namespace
    logger = logging.getLogger(__name__)
    logger.info(f"deleting claud-code agent from namespace: {agent_namespace}")
    try:
        kubernetes.client.AppsV1Api().delete_namespaced_deployment(
            name=metadata_name,
            namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted deployment")
    logger.info("deleting nginx configmap")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_config_map(
            name=f"{metadata_name}-nginx-config",
            namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx configmap")
    logger.info("deleting nginx deployment")
    try:
        kubernetes.client.AppsV1Api().delete_namespaced_deployment(
            name=f"{metadata_name}-nginx",
            namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx deployment")
    logger.info("deleting pvc")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_persistent_volume_claim(
            name=f"{metadata_name}-metadata",
            namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted metadata pvc")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_persistent_volume_claim(
            name=f"{metadata_name}-data",
            namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted data pvc")
    
    # Clean up RBAC resources
    try:
        kubernetes.client.RbacAuthorizationV1Api().delete_namespaced_role_binding(
            name=f"{metadata_name}-agent-binding",
            namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted role binding")
    
    try:
        kubernetes.client.RbacAuthorizationV1Api().delete_namespaced_role(
            name=f"{metadata_name}-agent-role",
            namespace=agent_namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted role")
    
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_service_account(
            name=f"{metadata_name}-agent-sa",
            namespace=agent_namespace
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
    
    
    