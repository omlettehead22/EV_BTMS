function q = qgen_charge(t, P)
%QGEN_CHARGE  Volumetric heat generation for fast-charge scenario (W/m^3).
%
% Calibrated to be close to qgen ≈ 94,023.8 W/m^3 used in a hybrid
% PCM + cold plate CFD model for NCR18650PF at 3C discharge.

q = 9.4e4;  % W/m^3.
end