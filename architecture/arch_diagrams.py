from diagrams import Cluster, Diagram, Edge
from diagrams.aws.network import Route53, ALB
from diagrams.aws.compute import ECR, EKS
from diagrams.aws.security import IAMRole
from diagrams.k8s.group import Namespace
from diagrams.k8s.network import Service
from diagrams.k8s.compute import Pod
from diagrams.k8s.rbac import ServiceAccount
from diagrams.onprem.vcs import Github
from diagrams.onprem.client import Users
from diagrams.custom import Custom

with Diagram("AWS-EKS Intern Lab(s)", show=True, filename="intro-aws-eks"):

    intern_lab_fqdn = Route53("lab.opswerks.net")
    intern_lab_lb = ALB("JupyterHub Ingress")
    jupyterhub_sso = Github("OAUTH Identity")

    with Cluster("Academy Intern(s)") as academy_interns:
        interns = Users("Jupyter Lab User(S)")

    with Cluster("AWS Service(s)") as aws_services:
        intern_k8s_cluster = EKS("Academy K8s Cluster")
        intern_lab_img_repo = ECR("Academy Lab App(s)")


    with Cluster("Academy K8s Cluster") as academy_cluster:
        with Cluster("Jupyter Orchestrator") as jupyter_orchestrator:
            jupyterhub_svc = Service("JupyterHub Service")
            jupyterhub_srv = Pod("JupyterHub Server")

        user_ns = []
        user_interface = []
        sample_api_lab = []
        k8s_account = []
        irsa = []
        for i in range(3):
            user_ns.append(Namespace(f"Intern Network {i}"))
            with Cluster(f"User Lab {i}") as jupyter_notebook:
                user_interface.append(Custom(f"Intern Notebook {i}", "./jupyter_notebook.png"))
                sample_api_lab.append(Pod(f"Flask API {i}"))
                k8s_account.append(ServiceAccount(f"K8s RBAC {i}"))
                irsa.append(IAMRole(f"AWS IAM Role {i}"))
            user_ns[i] >> user_interface[i]
            user_interface[i] >> sample_api_lab[i]
            k8s_account[i] << irsa[i]

    interns >> intern_lab_fqdn >> intern_k8s_cluster >> intern_lab_lb >>  jupyterhub_svc
    intern_k8s_cluster >> intern_lab_img_repo
    jupyterhub_svc >> jupyterhub_srv
    jupyterhub_srv >> intern_lab_img_repo
    jupyterhub_srv >> jupyterhub_sso
    jupyterhub_srv >> user_ns