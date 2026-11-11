function q = qgen_drive(t, P)
%QGEN_DRIVE  Volumetric heat generation for drive scenario (W/m^3).
%
% Uses values corresponding to ~0.5–2 W per 18650-type cell and
% below the 3C cold-plate hybrid case (~94 kW/m^3).

if t < 100
    q = 3e4;      % W/m^3 (≈0.5 W per cell).
elseif t < 300
    q = 1.0e5;    % W/m^3 (≈1.7 W per cell).
else
    q = 6e4;      % W/m^3 (≈1.0 W per cell).
end
end