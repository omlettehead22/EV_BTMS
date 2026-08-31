function [r,region] = build_grid_1D(P)
%BUILD_GRID_1D Cell-centred radial finite-volume grid.
%
% r      : control-volume centre positions [m]
% region : 1 = cell, 2 = PCM, 3 = casing

Nx = P.Nx;
R = P.r_case_outer;

if Nx < 3 || Nx ~= round(Nx)
    error('build_grid_1D:InvalidNx',...
        'P.Nx must be an integer greater than or equal to 3.');
end

dr = R/Nx;

% Cell-centred grid: first point is dr/2, not r = 0.
r = ((1:Nx).' - 0.5)*dr;

region = zeros(Nx,1);
region(r <= P.r_cell_outer) = 1;
region(r > P.r_cell_outer & r <= P.r_pcm_outer) = 2;
region(r > P.r_pcm_outer) = 3;

if any(region == 0)
    error('build_grid_1D:UnassignedRegion',...
        'One or more grid cells were not assigned a material.');
end

end