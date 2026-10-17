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


def test_solve_arithmetic_challenge_stutter_repetition_addition():
    challenge = (
        "A] lOoObS tEeR ]cLaW- eXerTs^ foR tY foRtY ]nEeWtOoNs umm, "
        "aNd/ tHe OtHeR ]anTeNnA eXerTs^ tWeNtY fIvE~ nOoToNs, wHaT| iS{ tHe }tOtAl- fOrCe<?"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "65.00"


def test_solve_arithmetic_challenge_explicit_multiplication_operator():
    challenge = (
        "A] lO b-St ErRr S^wImS| aNd Um, LoObBsTeR^ ClAwS~ ExErT< FoUrTeEn * ThReE ] nEu-ToNs, "
        "hOw/ mUcH^ ToTaL FoR cE? Lo.b s tErrR umm, velooocityyy, anNoTAtIoNs"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "42.00"


def test_solve_arithmetic_challenge_compound_multiplication_operator():
    challenge = (
        "AlOb] sT-Er^ lOoObBsTtErr\\ ClAw- FoRceEe] Is ThIrTy] TwO^ NeWtoNs~ * SeVeN{ NeWtOnS<, "
        "HoW/ MuCh^ ToTaL- FoRcE\\ iS? umm, lOo.oBbSsTtErr velawci tYyy umm"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "224.00"


def test_solve_arithmetic_challenge_reduced_by_subtraction():
    challenge = (
        "A] LoOoBbSsStTeErR] SwImS^ LiKe] A] nEuRoNnUmMlIkE,] ClAw] FoRcE] Of] TwEnTy] NiNe] NeWtOnS] "
        "-] ReDuCeD] By] SeVeN] NeWtOnS,] WhAt] Is] ThE] ReMaInInG] FoRcE?"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "22.00"


def test_solve_arithmetic_challenge_multiplied_by():
    challenge = (
        "A] Lo.bStEr^ ClAw- ExErTs/ TwEnTy TwO~ NeWtOoNs| AnD {iS} MuLlTiiPlIeD< By> ThReE, "
        "WhAt- Is/ ToTaL~ FoRcE?"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "66.00"


def test_solve_arithmetic_challenge_noise_prefix_and_explicit_plus():
    challenge = (
        "A] lO b-StErS^ wIth/ velAwCiTeE| is/ tWeNtY qThReE~ mEtErS\\pEr- MiNuTe, um, "
        "aNd- it/ spPlItts- inTo^ a/ doMiNaNcE] pUsH eLeMeNt| tHaT aDdS- sEvEn{ nEwToNs, "
        "hOw/ wOuLd- tHeIr] nEt/ 'sPeEd' ~ chAnGe/ iF^ yOu- aDd[ tWeNtY] qThReE + sEvEn?"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "30.00"


def test_solve_arithmetic_challenge_each_per_unit_multiplication():
    challenge = (
        "Ea]Ch Lo.bStEr ClAw^ ExErTs/ TwEnTy FoUr NoOoToNs~ Um AnD ThReE Lo~bStErS PuSh| ToGeThEr, "
        "WhAt'S< ThE ToTaL- FoRcE?"
    )
    res = solve_arithmetic_challenge(challenge)
    assert res == "72.00"
