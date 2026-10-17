"""Planning calculation for a binary future-target experiment, not evidence."""

from fractions import Fraction
from math import comb


def binary_plan(n=1000, alpha=Fraction(1, 200), alternative=Fraction(14, 25)):
    if type(n) is not int or n < 1 or not 0 < alpha < 1 or not Fraction(1, 2) < alternative < 1:
        raise ValueError("invalid fixed-sample design")
    alpha, alternative = Fraction(alpha), Fraction(alternative)
    tail = 2**n
    for critical in range(n + 1):
        if Fraction(tail, 2**n) <= alpha:
            break
        tail -= comb(n, critical)
    else:
        return {"n": n, "critical_successes": None, "reason": "no nonempty rejection region at this alpha"}
    a, b = alternative.numerator, alternative.denominator
    power = Fraction(sum(comb(n, k) * a**k * (b - a)**(n - k) for k in range(critical, n + 1)), b**n)
    return {"provenance": "MATHEMATICAL_DESIGN_NOT_EXPERIMENTAL_DATA", "n": n,
            "alpha": str(alpha), "null_success_probability": "1/2",
            "critical_successes": critical, "actual_null_tail": float(Fraction(tail, 2**n)),
            "alternative_success_probability": str(alternative), "power": float(power),
            "assumptions": "independent Bernoulli trials, fixed N, no optional stopping; full evaluability for stated power"}


if __name__ == "__main__":
    import json
    print(json.dumps(binary_plan(), indent=2))
