from cobra.core.Gene import parse_gpr

NOT_MASS_BALANCED_TERMS = {"SBO:0000627",  # EXCHANGE
                           "SBO:0000628",  # DEMAND
                           "SBO:0000629",  # BIOMASS
                           "SBO:0000631",  # PSEUDOREACTION
                           "SBO:0000632",  # SINK
                           }


def validate_model(model, errors=[], warnings=[]):
    errors = [i for i in errors]
    warnings = [i for i in warnings]
    for reaction in model.reactions:
        # test gpr
        try:
            parse_gpr(reaction.gene_reaction_rule)
        except SyntaxError:
            errors.append("reaction '%s' has invalid gpr '%s'" %
                          (reaction.id, reaction.gene_reaction_rule))
        if reaction.lower_bound > reaction.upper_bound:
            errors.append("reaction '%s' has lower_bound > upper_bound" %
                          reaction.id)
        if reaction.annotation.get("SBO") not in NOT_MASS_BALANCED_TERMS:
            balance = reaction.check_mass_balance()
            if balance:
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

    return {"errors": errors, "warnings": warnings, "objective": solution.f}
