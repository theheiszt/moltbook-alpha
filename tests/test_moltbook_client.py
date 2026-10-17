"""
Tests for MoltbookClient and Arithmetic Challenge Solver.
"""

from moltbook_client import solve_arithmetic_challenge, parse_number_words


def test_parse_number_words():
    assert parse_number_words(["thirty", "two"]) == 32.0
    assert parse_number_words(["eight"]) == 8.0
    assert parse_number_words(["one", "hundred", "five"]) == 105.0


def test_solve_arithmetic_challenge_subtraction():
    challenge = (
        "ThIs] Lo.oBbSsStErR^ Um] SwI^mS[ LiKe] A] MaChInE] At] ThIrTy TwO] MeTtErS] "
        "PeR] SeCoNd- BuT] AfTeR] A] DoMiNaNcE] ChAsE] It] SlOwS] By] EiGhT,] WhAt] Is] ThE] NeW] SpEeD?"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "24.00"


def test_solve_arithmetic_challenge_addition():
    challenge = (
        "ThIs] LoOoObStEr^ ClAw] FoRcE/ Is^ ThIrTy] NeWtOnS, Um] It] GaInS/ TwElVe] "
        "NeWtOnS In^ A DoMiNaNcE] FiGhT, WhAt] Is^ ThE ToTaL] FoRcE?"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "42.00"


def test_solve_arithmetic_challenge_multiplication():
    challenge = (
        "A] lOoO bSsT-Err S^wImS[ aT/ tWeNn-Ty fOuR mE^tErS PeR sEcOnD, Um, "
        "AnD MuL tIpLiEs ItS ClAw F{o}rCe Of/ fIfTeEn NeWToNs, HoW/ mUcH Is ThE PrOdUcT?"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "360.00"


def test_solve_arithmetic_challenge_broken_spacing_subtraction():
    challenge = (
        "A] L oB sT eR S^wImS /At TwEnTy ThReE~ cEnTiMeTeRs PeR/ SeCoNdS, Um - "
        "AnD LoOobssstt errr SlO wS bY SeVeN] cM/s, WhAt Is ThE/ nEw- VeLoOciTyyy? {hMm}"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "16.00"


def test_solve_arithmetic_challenge_three_fragment_word_addition():
    challenge = (
        "T]hE/ lO^bS t-Err LoOoBstErr sW/iMmS aT/ tW]eN tY- tHrEe^ cE^nTiMeTeRs PeR/ sEcOnD, "
        "AfTeR mOlTtInG iT iNcReAsEs^ bY/ sEvEn] cEnTiMeTeRs, wHaT Is/ tHe^ nEw- sPeE^d? um lxO bqS tEr"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "30.00"


def test_solve_arithmetic_challenge_multi_fragment_addition():
    challenge = (
        "A] lO b-St Er ~S wI mS[ aT/ tW/eN tY tH rEe]e CeN tI meT ers/ pEr- SeC oNd "
        "~aNd^ In CrEaSeS/ vElOo ocItY By[ fOuR, wH/aTs T]hE nEw- SpEeD?"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "27.00"
