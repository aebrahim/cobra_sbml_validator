from six import iteritems

from cobra.core.Gene import parse_gpr
from cobra.manipulation import check_mass_balance, check_reaction_bounds, \
    check_metabolite_compartment_formula


def validate_model(model, errors=[], warnings=[]):
    errors = [i for i in errors]
    warnings = [i for i in warnings]
    errors.extend(check_reaction_bounds(model))
    errors.extend(check_metabolite_compartment_formula(model))
    # test gpr
    for reaction in model.reactions:
        try:
            parse_gpr(reaction.gene_reaction_rule)
        except SyntaxError:
            errors.append("reaction '%s' has invalid gpr '%s'" %
                          (reaction.id, reaction.gene_reaction_rule))
    # test mass balance
    for reaction, balance in iteritems(check_mass_balance(model)):
        # check if it's a demand or exchange reaction
        if len(reaction.metabolites) == 1:
            warnings.append("reaction '%s' is not balanced. Should it "
                            "be annotated as a demand or exchange "
                            "reaction?" % reaction.id)
        elif "biomass" in reaction.id.lower():
            warnings.append("reaction '%s' is not balanced. Should it "
                            "be annotated as a biomass reaction?" %
                            reaction.id)
        else:
            warnings.append("reaction '%s' is not balanced for %s" %
                            (reaction.id, ", ".join(sorted(balance))))

    # try solving
    solution = model.optimize(solver="esolver")
    if solution.status != "optimal":
        errors.append("model can not be solved (status '%s')" %
                      solution.status)
        return {"errors": errors, "warnings": warnings}

    # if there is no objective, then we know why the objective was low
    if len(model.objective) == 0:
        warnings.append("model has no objective function")
    elif solution.f <= 0:
        warnings.append("model can not produce nonzero biomass")
    elif solution.f <= 1e-3:
        warnings.append("biomass flux %s too low" % str(solution.f))
    if len(model.objective) > 1:
        warnings.append("model should only have one reaction as the objective")

    return {"errors": errors, "warnings": warnings, "objective": solution.f}
