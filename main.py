import kopf
import logging
import kubernetes
import dotenv

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
    logger.info("creating nginx service")
    # create a service to serve the nginx deployment
    nginx_service = kubernetes.client.V1Service(
        metadata=kubernetes.client.V1ObjectMeta(name=nginx_name),
        spec=kubernetes.client.V1ServiceSpec(
            selector={"app": nginx_name},
            ports=[kubernetes.client.V1ServicePort(port=80)]
        )
    )
    # create the service
    kubernetes.client.CoreV1Api().create_namespaced_service(
        body=nginx_service,
        namespace="default"
    )
    logger.info("created nginx service")
    
    
    
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
    logger.info("deleting nginx service")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_service(
            name=f"{metadata_name}-nginx",
            namespace="default"
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx service")
    # PVC deletion removed (not created in create handler)
    # Custom object deletion removed (not needed, Kopf handles it)


@kopf.on.create('kopf.dev.claud-code', 'v1', 'claud-code')
def create_fn(body, name, namespace, logger, **kwargs):
    logging.info(f"A handler is called with body: {body}")
    metadata_name = body['metadata']['name']
    logger.info("updating claud-code")
    logger.info("updating claud-code")
    # create a deployment for wholelottahoopla/webagent:latest 
    # with metadata dir pvc 
    # and a data dir pvc 
    # and create a nginx deployment to serve the data dir
    # also create a service for webagent
    # create PVCs first
    core_v1_api = kubernetes.client.CoreV1Api()
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
            namespace=namespace
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 409:
            raise
    try:
        core_v1_api.create_namespaced_persistent_volume_claim(
            body=data_pvc,
            namespace=namespace
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
                    containers=[
                        kubernetes.client.V1Container(
                            name=metadata_name,
                            image="wholelottahoopla/webagent:latest",
                            image_pull_policy="Always",
                            args=[
                                "--port",
                                "8080",
                                "--working-dir",
                                "/data/output", 
                                "--metadata-dir",
                                "/data/metadata",
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
        namespace=namespace
    )
    logger.info("created deployment")
    logger.info("creating service")
    service = kubernetes.client.V1Service(
        metadata=kubernetes.client.V1ObjectMeta(name=metadata_name),
        spec=kubernetes.client.V1ServiceSpec(
            selector={"app": metadata_name},
            ports=[kubernetes.client.V1ServicePort(port=8080, target_port=8080, name="http")]
        )
    )
    kubernetes.client.CoreV1Api().create_namespaced_service(
        body=service,
        namespace=namespace
    )
    logger.info("created service")
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
            namespace=namespace,
            body=nginx_configmap
        )
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 409:  # AlreadyExists
            core_v1_api.replace_namespaced_config_map(
                name=configmap_name,
                namespace=namespace,
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
        namespace=namespace
    )
    logger.info("created nginx deployment")
    logger.info("creating nginx service")
    nginx_service = kubernetes.client.V1Service(
        metadata=kubernetes.client.V1ObjectMeta(name=nginx_name),
        spec=kubernetes.client.V1ServiceSpec(
            selector={"app": nginx_name},
            ports=[kubernetes.client.V1ServicePort(port=80, target_port=80, name="http")]
        )
    )
    kubernetes.client.CoreV1Api().create_namespaced_service(
        body=nginx_service,
        namespace=namespace
    )
    logger.info("created nginx service")




# delete the deployment and service for the claud-code and nginx and remove the pvc
@kopf.on.delete('kopf.dev.claud-code', 'v1', 'claud-code')
def delete_fn(body, name, namespace, logger, **kwargs):
    from kubernetes.client.exceptions import ApiException
    logging.info(f"A handler is called with body: {body}")
    metadata_name = body['metadata']['name']
    logger.info("deleting deployment")
    try:
        kubernetes.client.AppsV1Api().delete_namespaced_deployment(
            name=metadata_name,
            namespace=namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted deployment")
    logger.info("deleting service")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_service(
            name=metadata_name,
            namespace=namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted service")
    logger.info("deleting pvc")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_persistent_volume_claim(
            name=f"{metadata_name}-metadata",
            namespace=namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted metadata pvc")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_persistent_volume_claim(
            name=f"{metadata_name}-data",
            namespace=namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted data pvc")
    logger.info("deleted claud-code")
    logger.info("deleting nginx deployment")
    try:
        kubernetes.client.AppsV1Api().delete_namespaced_deployment(
            name=f"{metadata_name}-nginx",
            namespace=namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx deployment")
    logger.info("deleting nginx service")
    try:
        kubernetes.client.CoreV1Api().delete_namespaced_service(
            name=f"{metadata_name}-nginx",
            namespace=namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise
    logger.info("deleted nginx service")
    logger.info("deleted claud-code")
    logger.info("deleted claud-code")
    
    
    