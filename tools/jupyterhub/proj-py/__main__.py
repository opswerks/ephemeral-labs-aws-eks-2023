import pulumi
from infra import lab_cluster, lab_cluster_oidc, lab_s3_access_role, ecr_repo, jupyter_img, lab_svc_account, jupyter_fqdn

pulumi.export("eks_arn", lab_cluster.arn)
pulumi.export("eks_oidc", lab_cluster_oidc)
pulumi.export("iam_irsa", lab_s3_access_role.arn)
pulumi.export("lab_repo", ecr_repo.repository_url)
pulumi.export("image_name", jupyter_img.base_image_name)
pulumi.export("k8s_irsa", lab_svc_account.metadata["name"])
pulumi.export("lab-fqdn", jupyter_fqdn.fqdn)