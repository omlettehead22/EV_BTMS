function [A_bc,b_bc] = apply_bc_liquid_1D(...
    A_diff,C_cap,r,region,P,T_coolant,h_liq)
%APPLY_BC_LIQUID_1D Conservative outer liquid-convection boundary.
%
% C_cap is retained in the interface for compatibility.

A_bc = A_diff;
b_bc = zeros(size(r));

if h_liq < 0
    error('apply_bc_liquid_1D:InvalidH',...
        'The convection coefficient cannot be negative.');
end

if h_liq == 0
    return;
end

Nx = numel(r);
dr = r(2)-r(1);
i = Nx;

switch region(i)
    case 1
        kOuter = P.k_cell;
    case 2
        kOuter = P.k_pcm;
    case 3
        kOuter = P.k_case;
    otherwise
        error('apply_bc_liquid_1D:UnknownRegion',...
            'Unknown outer material region.');
end

Rout = r(end)+dr/2;
Rwest = r(end)-dr/2;

outerArea = 2*pi*Rout*P.L_axial;
outerVolume = pi*(Rout^2-Rwest^2)*P.L_axial;

overallConductance = outerArea / ...
    (dr/(2*kOuter)+1/h_liq); % W/K

sinkCoefficient = overallConductance/outerVolume;

A_bc(i,i) = A_bc(i,i)-sinkCoefficient;
b_bc(i) = b_bc(i)+sinkCoefficient*T_coolant;

end