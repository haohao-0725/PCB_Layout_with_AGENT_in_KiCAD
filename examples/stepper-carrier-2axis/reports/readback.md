Gerber files
  stepper_carrier-B_Cu.gbl                     Copper,L4,Bot
  stepper_carrier-B_Mask.gbs                   Soldermask,Bot
  stepper_carrier-B_Silkscreen.gbo             Legend,Bot
  stepper_carrier-Edge_Cuts.gm1                Profile,NP
  stepper_carrier-F_Cu.gtl                     Copper,L1,Top
  stepper_carrier-F_Mask.gts                   Soldermask,Top
  stepper_carrier-F_Silkscreen.gto             Legend,Top
  stepper_carrier-In1_Cu.g1                    Copper,L2,Inr
  stepper_carrier-In2_Cu.g2                    Copper,L3,Inr

Copper layer order
| Layer | Position | File |
|---|---|---|
| L1 | top | `stepper_carrier-F_Cu.gtl` |
| L2 | inner | `stepper_carrier-In1_Cu.g1` |
| L3 | inner | `stepper_carrier-In2_Cu.g2` |
| L4 | bottom | `stepper_carrier-B_Cu.gbl` |

Board outline
  126.000 x 146.000 mm (line centres)

Drill files
  stepper_carrier-NPTH.drl  (NonPlated,1,4,NPTH)
    NonPlated  hole  Ø3.200 mm  x 4
  stepper_carrier-PTH.drl  (Plated,1,4,PTH)
    Plated     hole  Ø0.800 mm  x 20
    Plated     hole  Ø1.000 mm  x 184
    Plated     hole  Ø1.300 mm  x 4
    Plated     hole  Ø1.600 mm  x 14

Totals: plated 222, non-plated 4

Readback: PASS
