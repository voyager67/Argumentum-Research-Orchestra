from argumentum.server.api import Principal

def test_principal_keeps_workspace_identity_and_role():
    p=Principal(tenant_id="tenant-a",role="researcher")
    assert p.tenant_id=="tenant-a" and p.role=="researcher" and not p.platform_admin
