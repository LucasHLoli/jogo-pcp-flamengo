import pulp


def test_cbc_disponivel():
    prob = pulp.LpProblem("smoke", pulp.LpMinimize)
    x = pulp.LpVariable("x", lowBound=0)
    prob += x
    prob += x >= 1
    # PuLP 3.x removeu tmpDir de PULP_CBC_CMD; o CBC usa o tempdir do sistema.
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[status] == "Optimal"
    assert pulp.value(x) == 1.0
