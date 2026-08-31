function [A_diff,C_cap] = build_matrices_1D(r,region,P)
%BUILD_MATRICES_1D Conservative cylindrical finite-volume matrices.
%
% Governing semi-discrete equation:
%
%   C_cap*dT/dt = A_diff*T + q + b
%
% A_diff has units W/(m^3 K).
% C_cap has units J/(m^3 K).

Nx = numel(r);

if Nx < 2
    error('build_matrices_1D:InsufficientGrid',...
        'At least two radial control volumes are required.');
end

dr = r(2)-r(1);
Lz = P.L_axial;

rho = zeros(Nx,1);
cp  = zeros(Nx,1);
k   = zeros(Nx,1);

for i = 1:Nx
    switch region(i)
        case 1
            rho(i) = P.rho_cell;
            cp(i)  = P.cp_cell;
            k(i)   = P.k_cell;

        case 2
            rho(i) = P.rho_pcm;
            cp(i)  = P.cp_pcm_solid;
            k(i)   = P.k_pcm;

        case 3
            rho(i) = P.rho_case;
            cp(i)  = P.cp_case;
            k(i)   = P.k_case;

        otherwise
            error('build_matrices_1D:UnknownRegion',...
                'Unknown region identifier at node %d.',i);
    end
end

rWest = max(r-dr/2,0);
rEast = r+dr/2;

volume = pi*(rEast.^2-rWest.^2)*Lz;

A_diff = sparse(Nx,Nx);
C_cap  = spdiags(rho.*cp,0,Nx,Nx);

% Each internal face contributes equal and opposite heat flow
% to the two adjoining control volumes.
for i = 1:Nx-1

    rFace = 0.5*(r(i)+r(i+1));
    faceArea = 2*pi*rFace*Lz;

    % Harmonic mean preserves heat-flux continuity across
    % dissimilar material interfaces.
    kFace = 2*k(i)*k(i+1)/(k(i)+k(i+1));

    conductance = kFace*faceArea/dr; % W/K

    A_diff(i,i)       = A_diff(i,i) ...
        - conductance/volume(i);
    A_diff(i,i+1)     = A_diff(i,i+1) ...
        + conductance/volume(i);

    A_diff(i+1,i)     = A_diff(i+1,i) ...
        + conductance/volume(i+1);
    A_diff(i+1,i+1)   = A_diff(i+1,i+1) ...
        - conductance/volume(i+1);
end

end