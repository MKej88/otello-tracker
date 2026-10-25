# Code Scanning – gjennomgang 25. oktober 2026

Denne gjennomgangen gjelder den planlagte oppryddingen etter 16 funn vist i
GitHub Code Scanning. Funnene er verifisert mot SARIF-resultatene i GitHub
Actions, men faktisk antall åpne varsler må avstemmes i GitHubs Security-fane.

## zizmor – 10 like ref-version-mismatch

Alle treffene gjelder `actions/setup-python` låst til
`5fda3b95a4ea91299a34e894583c3862153e4b97` med kommentaren `# v7`.
GitHub-taggen `v7.0.0` peker til **denne eksakte commit-hashen**, mens den
flytende hovedversjonstaggen `v7` peker til en nyere commit. Kommentarene
rettes derfor til `# v7.0.0`, uten å endre kode, rettigheter eller action-SHA.
Omfatter ti forekomster fordelt på åtte workflowfiler.

## OpenSSF Scorecard – seks øvrige funn

| Funn | Vurdering/oppfølging |
| --- | --- |
| BranchProtection | Beskyttelse av `main` håndhever 11 påkrevde tester. Den krever ikke menneskelig review. Krav om en uavhengig godkjenner bør bare aktiveres når en slik gjennomgang faktisk er tilgjengelig. |
| CodeReview | Scorecard ser ingen menneskelig godkjenning i siste endringssett. Automatisert testing er ikke en erstatning for menneskelig review, men vi aktiverer ikke et kunstig godkjenningskrav bare for poeng. |
| Fuzzing | Fuzztester finnes ikke. Kan vurderes separat for parserne som leser eksterne dokumenter og feeds, ved en konkret trusselmodell og testplan. |
| License | Repositoriet har ikke lisensfil. Eier må velge rettighetsvilkår; en åpen lisens må **ikke** opprettes uten eierbeslutning. |
| Maintained | Repoet er yngre enn 90 dager etter Scorecards registrering. Ikke en kodefeil; kontroller på nytt når historikken er lang nok. |
| CIIBestPractices | Ingen OpenSSF Best Practices badge. Frivillig modenhetsprogram, ikke en dokumentert sårbarhet. |

Disse seks funnene er **vurdert, ikke rettet eller avvist**. De bør ikke
markeres som løst uten at faktisk tilhørende tiltak er utført.

**Kilder:** GitHub Actions: OpenSSF Scorecard-kjøring
`40186990550`; GitHub Actions security analysis `40184478332`; offisielle
`actions/setup-python` Git refs `v7.0.0` og `v7`.
