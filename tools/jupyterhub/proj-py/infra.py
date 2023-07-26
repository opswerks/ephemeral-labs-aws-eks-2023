import base64
import json
# import yaml
import pulumi_aws as aws
import pulumi_docker as docker
import pulumi_kubernetes as k8s
from pulumi import ResourceOptions
from pulumi_command import local
from pulumi_kubernetes.helm.v3 import Chart, ChartOpts, FetchOpts
from utils import data, generate_kube_config, gh_client_id, gh_client_secret, values_tpl

# AWS-EKS (K8s) Connection Setup
lab_cluster = aws.eks.get_cluster(name=data.get("eks-cluster"))

lab_cluster_authn = aws.eks.get_cluster_auth(name=data.get("eks-cluster"))

k8s_provider = k8s.Provider(
                   "k8s-provider",
                   kubeconfig=generate_kube_config(
                                server=lab_cluster.endpoint,
                                cert=lab_cluster.certificate_authorities[0].data,
                                token=lab_cluster_authn.token
                              )
                   )

# AWS ECR Image Repository
ecr_repo = aws.ecr.Repository(
               "ecr-repo",
               name=data.get("ecr-repo"),
               force_delete=False,
               image_tag_mutability="MUTABLE",
               tags=data.get("tags")
           )

ecr_token = aws.ecr.get_authorization_token(registry_id=data.get("account"))

ecr_username = base64.b64decode(ecr_token.authorization_token).decode('utf-8').split(':')[0]

ecr_password = base64.b64decode(ecr_token.authorization_token).decode('utf-8').split(':')[1]

ecr_configjson = json.dumps({
    "auths": {
        f"{data.get('account')}.dkr.ecr.us-west-2.amazonaws.com/{data.get('account')}": {
            "username": f"{ecr_username}",
            "password": f"{ecr_password}"
        }
    }
})

ecr_pull_secret = k8s.core.v1.Secret(
                      "ecr-docker-config",
                      type="kubernetes.io/dockerconfigjson",
                      metadata=k8s.meta.v1.ObjectMetaArgs(
                                   name="regcred",
                                   namespace=data.get("namespace")
                               ),
                      data={
                                ".dockerconfigjson": f"{base64.b64encode(ecr_configjson.encode('utf-8')).decode('utf-8')}"
                           },
                      opts=ResourceOptions(provider=k8s_provider)
                  )

jupyter_img = docker.Image(
                     "lab-img",
                     build=docker.DockerBuildArgs(dockerfile="./image/Dockerfile", platform="linux/amd64"),
                     image_name=ecr_repo.repository_url.apply(lambda repository_url: f"{repository_url}:latest"),
                     registry=docker.RegistryArgs(
                                     username=ecr_username,
                                     password=ecr_password,
                                     server=ecr_repo.repository_url,
                              )
              )

# Additional AWS-EKS service(s)/plugin(s)
aws_autoscaler = Chart(
                 "cluster-autoscaler",
                 ChartOpts(
                     chart="cluster-autoscaler",
                     fetch_opts=FetchOpts(
                        repo="https://kubernetes.github.io/autoscaler"
                     ),
                     namespace="kube-system",
                     values={
                         "cloudProvider": "aws",
                         "awsRegion": "us-west-2",
                         "autoDiscovery": {
                             "enabled": "true",
                             "clusterName": f"{data.get('eks-cluster')}",
                         },
                         "podLabels": {
                             "app": "cluster-autoscaler"
                         }
                     }
                 )
                 )

# JupyterHub Deployment Prerequisites
gh_creds = k8s.core.v1.Secret(
               "gh-credentials",
               type="Opaque",
               metadata=k8s.meta.v1.ObjectMetaArgs(
                            name=data.get("gh-secret"),
                            namespace=data.get("namespace")
                            ),
               data={
                        "id": f"{base64.b64encode(gh_client_id.encode('utf-8')).decode('utf-8')}",
                        "secret": f"{base64.b64encode(gh_client_secret.encode('utf-8')).decode('utf-8')}"
                    },
               opts=ResourceOptions(provider=k8s_provider)
               )



jupyter_crole = k8s.rbac.v1.ClusterRole(
                    f"{data.get('chart-name')}-cluster-role",
                    metadata=k8s.meta.v1.ObjectMetaArgs(name=f"{data.get('chart-name')}-cluster-role"),
                    rules=[
                        {
                            "apiGroups": ["*"],
                            "resources": ["*"],
                            "verbs": [
                                "get",
                                "list",
                                "watch",
                                "create",
                                "update",
                                "patch",
                                "delete"
                            ],
                        }
                    ],
                    opts=ResourceOptions(provider=k8s_provider)
                )

jupyter_svc_account = k8s.core.v1.ServiceAccount(f"{data.get('chart-name')}-service-account",
                          metadata=k8s.meta.v1.ObjectMetaArgs(
                                       name=f"{data.get('chart-name')}-svc-account",
                                       namespace=f"{data.get('namespace')}"
                                   ),
                          opts=ResourceOptions(provider=k8s_provider)
                      )

jupyter_crbinding = k8s.rbac.v1.ClusterRoleBinding(
    f"{data.get('chart-name')}-crole-binding",
    metadata=k8s.meta.v1.ObjectMetaArgs(
                 name=f"{data.get('chart-name')}-crole-binding",
                 namespace=f"{data.get('namespace')}"
             ),
    subjects=[k8s.rbac.v1.SubjectArgs(
        kind="ServiceAccount",
        name=f"{data.get('chart-name')}-svc-account",
        namespace=f"{data.get('namespace')}",
    )],
    role_ref=k8s.rbac.v1.RoleRefArgs(
        api_group="rbac.authorization.k8s.io",
        kind="ClusterRole",
        name=jupyter_crole.metadata["name"],
    ),
    opts=ResourceOptions(provider=k8s_provider),
)

# User-specific environment setup
lab_cluster_oidc = lab_cluster.identities[0].oidcs[0].issuer

lab_s3_access_role = aws.iam.Role(
                         "lab-s3-access-role",
                         assume_role_policy=f"""{{
                            "Version": "2012-10-17",
                            "Statement": [
                                {{
                                    "Effect": "Allow",
                                    "Principal": {{
                                        "Federated": "arn:aws:iam::{data.get("account")}:oidc-provider/{lab_cluster_oidc.replace('https://','')}"
                                    }},
                                    "Action": "sts:AssumeRoleWithWebIdentity",
                                    "Condition": {{
                                        "StringEquals": {{
                                            "{lab_cluster_oidc.replace('https://','')}:aud": "sts.amazonaws.com",
                                            "{lab_cluster_oidc.replace('https://','')}:sub": "system:serviceaccount:{data.get("user-namespace")}:{data.get("user-svc-account")}-svc-account"
                                        }}
                                    }}
                                }}
                            ]                         
                         }}""",
                     )

lab_s3_access_policy = aws.iam.RolePolicyAttachment("lab-s3-access-policy",
                           role=lab_s3_access_role.name,
                           policy_arn="arn:aws:iam::aws:policy/AmazonS3FullAccess",
                       )

lab_svc_account = k8s.core.v1.ServiceAccount(f"{data.get('user-svc-account')}-service-account",
                      metadata=k8s.meta.v1.ObjectMetaArgs(
                                   annotations={
                                        "eks.amazonaws.com/role-arn": lab_s3_access_role.arn
                                   },
                                   name=f"{data.get('user-svc-account')}-svc-account",
                                   namespace=f"{data.get('user-namespace')}"
                               ),
                      opts=ResourceOptions(provider=k8s_provider)
                  )

lab_svc_role = k8s.rbac.v1.Role(f"{data.get('user-svc-account')}-role",
                   metadata=k8s.meta.v1.ObjectMetaArgs(
                                name=f"{data.get('user-svc-account')}-role",
                                namespace=f"{data.get('user-namespace')}"
                   ),
                   rules=[
                        {
                            "apiGroups": ["*"],
                            "resources": [
                                "pods",
                                "secrets",
                                "configmaps",
                                "services"
                            ],
                            "verbs": [
                                "get",
                                "list",
                                "watch",
                                "create",
                                "update",
                                "patch",
                                "delete"
                            ],
                        }
                   ],
                   opts=ResourceOptions(provider=k8s_provider)
               )

lab_svc_rbinding = k8s.rbac.v1.RoleBinding(
    f"{data.get('user-svc-account')}-role-binding",
    metadata=k8s.meta.v1.ObjectMetaArgs(
                 name=f"{data.get('user-svc-account')}-role-binding",
                 namespace=f"{data.get('user-namespace')}"
             ),
    subjects=[k8s.rbac.v1.SubjectArgs(
        kind="ServiceAccount",
        name=f"{data.get('user-svc-account')}-svc-account",
        namespace=f"{data.get('user-namespace')}",
    )],
    role_ref=k8s.rbac.v1.RoleRefArgs(
        api_group="rbac.authorization.k8s.io",
        kind="Role",
        name=lab_svc_role.metadata["name"],
    ),
    opts=ResourceOptions(provider=k8s_provider),
)

lab_quota = k8s.core.v1.ResourceQuota(
                "lab-quota",
                metadata=k8s.meta.v1.ObjectMetaArgs(
                             namespace=f"{data.get('user-namespace')}",
                ),
                spec=k8s.core.v1.ResourceQuotaSpecArgs(
                         hard={
                                "pods": "3",
                                "requests.memory": "5Gi",
                         }
                     )
            )

values_render = values_tpl.format(
    app_name=data.get('tags')['purpose'],
    lab_name=data.get('chart-name'),
    dns_zone=data.get('user-domain'),
    secret_name=data.get('gh-secret'),
    git_org=data.get('org-allow'),
    hub_ns=data.get('namespace'),
    svc_account=data.get('chart-name'),
    usr_svc_account=data.get('user-svc-account'),
    repo_url=f"{data.get('account')}.dkr.ecr.us-west-2.amazonaws.com/{data.get('ecr-repo')}"
)

with open("values.yml", "w") as config_file:
    config_file.write(values_render)

# Current Pulumi bug for helmv3:
# - https://github.com/pulumi/pulumi-kubernetes/issues/555
# jupyter_hub = Chart(
#                      "jupyter-hub-deployment",
#                      ChartOpts(
#                          chart=data.get("chart-name"),
#                          fetch_opts=FetchOpts(
#                             repo="https://jupyterhub.github.io/helm-chart/"
#                          ),
#                          namespace=data.get("namespace")
#                          values=yaml.safe_load(config_file)
#                      )
#               )

if data.get("deploy") == True:
    deploy_jupyter = local.Command(
    # Increment "jupyter_install_#" to let helm run
                     "jupyter-install-11",
                     create=f"helm upgrade --install -n {data.get('namespace')} {data.get('chart-name')} {data.get('chart-name')}/{data.get('chart-name')} -f ./values.yml"
                     )
elif data.get("deploy") == False:
    destroy_jupyter = local.Command(
        # Increment "jupyter_install_#" to let helm run
        "jupyter-destroy",
        create=f"helm uninstall -n {data.get('namespace')} {data.get('chart-name')} --dry-run --debug"
    )

jupyter_cert = aws.acm.get_certificate(domain=f"*.{data.get('user-domain')}", types=["AMAZON_ISSUED"])

jupyter_alb = k8s.networking.v1.Ingress(
                  "jupyter-lb",
                  metadata=k8s.meta.v1.ObjectMetaArgs(
                               name="jupyterhub",
                               namespace=data.get("namespace"),
                               annotations={
                                    "kubernetes.io/ingress.class": "alb",
                                    "alb.ingress.kubernetes.io/scheme": "internet-facing",
                                    "alb.ingress.kubernetes.io/listen-ports": '[{"HTTPS":443}, {"HTTP":80}]',
                                    "alb.ingress.kubernetes.io/certificate-arn": jupyter_cert.arn
                               }
                           ),
                  spec=k8s.networking.v1.IngressSpecArgs(
                           rules=[k8s.networking.v1.IngressRuleArgs(
                                     http=k8s.networking.v1.HTTPIngressRuleValueArgs(
                                              paths=[
                                                  k8s.networking.v1.HTTPIngressPathArgs(
                                                      backend=k8s.networking.v1.IngressBackendArgs(
                                                                  service=k8s.networking.v1.IngressServiceBackendArgs(
                                                                              name="proxy-public",
                                                                              port=k8s.networking.v1.ServiceBackendPortArgs(
                                                                                       number=80
                                                                              )
                                                                          )
                                                              ),
                                                  path="/",
                                                  path_type="Prefix"
                                                  )
                                              ],
                                          )
                                 )]
                       )
              )

lab_zone = aws.route53.get_zone(name=data.get("user-domain"))

jupyter_fqdn = aws.route53.Record(
                   "jupyter-fqdn",
                   zone_id=lab_zone.zone_id,
                   name=f"{data.get('tags')['purpose']}-{data.get('chart-name')}.{data.get('user-domain')}",
                   type="CNAME",
                   ttl=300,
                   records=[
                       jupyter_alb.status.load_balancer.ingress[0].hostname
                   ]
               )