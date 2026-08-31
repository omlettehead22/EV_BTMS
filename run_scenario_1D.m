function results = run_scenario_1D(...
    P,scenarioType,bcType,hLevel,T_env,varargin)
%RUN_SCENARIO_1D Conservative transient radial thermal model.
%
% Optional inputs:
%   varargin{1}: event-duration override [s]
%   varargin{2}: heat-generation override [W/m^3] or function handle
%
% Examples:
%   run_scenario_1D(P,'charge','liquid','mid',Tcoolant)
%   run_scenario_1D(P,'charge','liquid','mid',Tcoolant,600,0)

%% Optional inputs

tEndOverride = [];
qgenOverride = [];

if numel(varargin) >= 1
    tEndOverride = varargin{1};
end

if numel(varargin) >= 2
    qgenOverride = varargin{2};
end

%% Grid and matrices

[r,region] = build_grid_1D(P);
[A_diff,C_cap_base] = build_matrices_1D(r,region,P);

Nx = numel(r);
dr = r(2)-r(1);
Lz = P.L_axial;

rWest = max(r-dr/2,0);
rEast = r+dr/2;

shellVol = pi*(rEast.^2-rWest.^2)*Lz;

cellNodes = region == 1;
pcmNodes  = region == 2;
caseNodes = region == 3;

if ~any(cellNodes)
    error('run_scenario_1D:NoCellNodes',...
        'The grid contains no battery-cell control volumes.');
end

%% Heat-transfer coefficient

switch lower(bcType)
    case 'air'
        switch lower(hLevel)
            case 'low'
                h = P.h_air_low;
            case 'mid'
                h = P.h_air_mid;
            case 'high'
                h = P.h_air_high;
            otherwise
                error('run_scenario_1D:UnknownAirLevel',...
                    'Unknown air-cooling level: %s',hLevel);
        end

    case 'liquid'
        switch lower(hLevel)
            case 'low'
                h = P.h_liq_low;
            case 'mid'
                h = P.h_liq_mid;
            case 'high'
                h = P.h_liq_high;
            otherwise
                error('run_scenario_1D:UnknownLiquidLevel',...
                    'Unknown liquid-cooling level: %s',hLevel);
        end

    case {'adiabatic','none'}
        h = 0;

    otherwise
        error('run_scenario_1D:UnknownBC',...
            'Unknown boundary-condition type: %s',bcType);
end

%% Time vector

if ~isempty(tEndOverride)
    tEnd = tEndOverride;
else
    switch lower(scenarioType)
        case 'drive'
            tEnd = P.t_end_drive;
        case 'charge'
            tEnd = P.t_end_charge;
        otherwise
            error('run_scenario_1D:UnknownScenario',...
                'Unknown scenario type: %s',scenarioType);
    end
end

Nt = max(1,round(tEnd/P.dt));
dt = tEnd/Nt;
t_vec = (0:Nt).'*dt;

%% Initial condition

if isfield(P,'T_initial')
    T = ones(Nx,1)*P.T_initial;
else
    T = ones(Nx,1)*T_env;
end

%% Boundary matrix

switch lower(bcType)
    case 'air'
        [A_bc,b_bc] = apply_bc_air_1D(...
            A_diff,C_cap_base,r,region,P,T_env,h);

    case 'liquid'
        [A_bc,b_bc] = apply_bc_liquid_1D(...
            A_diff,C_cap_base,r,region,P,T_env,h);

    otherwise
        A_bc = A_diff;
        b_bc = zeros(Nx,1);
end

%% Boundary conductance for energy accounting

if h > 0
    switch region(end)
        case 1
            kOuter = P.k_cell;
        case 2
            kOuter = P.k_pcm;
        case 3
            kOuter = P.k_case;
    end

    outerRadius = r(end)+dr/2;
    outerArea = 2*pi*outerRadius*Lz;

    G_boundary = outerArea / ...
        (dr/(2*kOuter)+1/h);
else
    outerArea = 2*pi*(r(end)+dr/2)*Lz;
    G_boundary = 0;
end

%% Storage

Tmax = zeros(Nt+1,1);
Tmin = zeros(Nt+1,1);
dTmax = zeros(Nt+1,1);
T_hist = zeros(Nx,Nt+1);
phi_pcm = zeros(Nt+1,1);

dE_gen = zeros(Nt+1,1);
dE_bc = zeros(Nt+1,1);
dE_cell = zeros(Nt+1,1);
dE_pcm = zeros(Nt+1,1);
dE_case = zeros(Nt+1,1);
dE_stored = zeros(Nt+1,1);
dE_residual = zeros(Nt+1,1);

nonlinearIterations = zeros(Nt+1,1);

T_hist(:,1) = T;
Tmax(1) = max(T(cellNodes));
Tmin(1) = min(T(cellNodes));
dTmax(1) = Tmax(1)-Tmin(1);

phi_pcm(1) = compute_pcm_fraction(...
    T,region,P,shellVol);

rhoVector = material_density(region,P);

%% Time stepping

for n = 1:Nt

    time = t_vec(n);

    %% Heat generation

    if ~isempty(qgenOverride)

        if isa(qgenOverride,'function_handle')
            qgen = qgenOverride(time);
        else
            qgen = qgenOverride;
        end

    else

        switch lower(scenarioType)
            case 'drive'
                qgen = qgen_drive(time,P);
            case 'charge'
                qgen = qgen_charge(time,P);
            otherwise
                error('run_scenario_1D:UnknownScenario',...
                    'Unknown scenario type.');
        end
    end

    if ~isscalar(qgen) || ~isfinite(qgen)
        error('run_scenario_1D:InvalidHeatSource',...
            'Heat generation must be one finite scalar.');
    end

    q_vec = zeros(Nx,1);
    q_vec(cellNodes) = qgen;

    %% Nonlinear apparent-heat-capacity iteration

    T_old = T;
    T_guess = T_old;

    converged = false;

    for iteration = 1:P.nonlinear_max_iterations

        C_cap = update_capacity(...
            C_cap_base,T_guess,region,P);

        M_left = C_cap/dt-A_bc;
        rhs = (C_cap/dt)*T_old+q_vec+b_bc;

        T_candidate = M_left\rhs;

        if any(~isfinite(T_candidate))
            error('run_scenario_1D:NonFiniteTemperature',...
                'Non-finite temperature encountered at t = %.3f s.',...
                time+dt);
        end

        change = max(abs(T_candidate-T_guess));

        if change < P.nonlinear_tolerance
            T_guess = T_candidate;
            converged = true;
            break;
        end

        relaxation = P.nonlinear_relaxation;

        T_guess = relaxation*T_candidate ...
                  +(1-relaxation)*T_guess;
    end

    if ~converged
        warning('run_scenario_1D:NonlinearIteration',...
            ['PCM iteration did not reach tolerance at ',...
             't = %.3f s; final change = %.3e K.'],...
             time+dt,change);
    end

    nonlinearIterations(n+1) = iteration;
    T = T_guess;

    %% Energy accounting

    dE_gen(n+1) = sum(q_vec.*shellVol)*dt;

    % Positive when heat leaves the thermal domain.
    dE_bc(n+1) = ...
        G_boundary*(T(end)-T_env)*dt;

    hOld = specific_enthalpy(T_old,region,P);
    hNew = specific_enthalpy(T,region,P);

    nodeEnergyChange = ...
        rhoVector.*shellVol.*(hNew-hOld);

    dE_cell(n+1) = sum(nodeEnergyChange(cellNodes));
    dE_pcm(n+1) = sum(nodeEnergyChange(pcmNodes));
    dE_case(n+1) = sum(nodeEnergyChange(caseNodes));

    dE_stored(n+1) = sum(nodeEnergyChange);

    dE_residual(n+1) = ...
        dE_gen(n+1)-dE_bc(n+1)-dE_stored(n+1);

    %% Store thermal fields

    T_hist(:,n+1) = T;

    Tmax(n+1) = max(T(cellNodes));
    Tmin(n+1) = min(T(cellNodes));
    dTmax(n+1) = Tmax(n+1)-Tmin(n+1);

    phi_pcm(n+1) = compute_pcm_fraction(...
        T,region,P,shellVol);
end

%% Auxiliary power

[P_aux,E_aux] = aux_power(...
    P,bcType,hLevel,t_vec);

%% Event totals

E_generated = sum(dE_gen);
E_rejected = sum(dE_bc);
E_stored = sum(dE_stored);
E_balance_residual = sum(dE_residual);

if abs(E_generated) > eps
    balance_error_pct = ...
        100*abs(E_balance_residual)/abs(E_generated);
else
    balance_error_pct = 0;
end

%% Results structure

results.t = t_vec;
results.r = r;
results.region = region;
results.shellVol = shellVol;

results.T_hist = T_hist;
results.Tmax = Tmax;
results.Tmin = Tmin;
results.dTmax = dTmax;
results.phi_pcm = phi_pcm;

results.P_aux = P_aux;
results.E_aux = E_aux;

% Retain existing field names for compatibility.
% These fields contain energy increments in J.
results.Q_gen = dE_gen;
results.Q_bc = dE_bc;
results.Q_pcm = dE_pcm;

results.dE_gen = dE_gen;
results.dE_bc = dE_bc;
results.dE_cell = dE_cell;
results.dE_pcm = dE_pcm;
results.dE_case = dE_case;
results.dE_stored = dE_stored;
results.dE_residual = dE_residual;

results.E_generated = E_generated;
results.E_rejected = E_rejected;
results.E_stored = E_stored;
results.E_balance_residual = E_balance_residual;
results.balance_error_pct = balance_error_pct;

results.h = h;
results.T_environment = T_env;
results.outerArea = outerArea;
results.nonlinearIterations = nonlinearIterations;

end


function C_cap = update_capacity(...
    C_cap_base,T,region,P)
%UPDATE_CAPACITY Apparent heat capacity of PCM.

C_cap = C_cap_base;

pcmNodes = find(region == 2);

deltaTm = P.Tm_liquid-P.Tm_solid;

if deltaTm <= 0
    error('run_scenario_1D:InvalidMeltingInterval',...
        'P.Tm_liquid must be greater than P.Tm_solid.');
end

cpMushy = 0.5*(P.cp_pcm_solid+P.cp_pcm_liquid) ...
          +P.L_pcm/deltaTm;

for j = 1:numel(pcmNodes)

    i = pcmNodes(j);

    if T(i) <= P.Tm_solid
        cpEffective = P.cp_pcm_solid;

    elseif T(i) >= P.Tm_liquid
        cpEffective = P.cp_pcm_liquid;

    else
        cpEffective = cpMushy;
    end

    C_cap(i,i) = P.rho_pcm*cpEffective;
end

end


function phi = compute_pcm_fraction(...
    T,region,P,shellVol)
%COMPUTE_PCM_FRACTION Volume-weighted PCM liquid fraction.

pcmNodes = region == 2;

if ~any(pcmNodes)
    phi = 0;
    return;
end

deltaTm = P.Tm_liquid-P.Tm_solid;

if deltaTm <= 0
    phi = 0;
    return;
end

localFraction = ...
    (T(pcmNodes)-P.Tm_solid)/deltaTm;

localFraction = min(max(localFraction,0),1);

weights = shellVol(pcmNodes);

phi = sum(localFraction.*weights)/sum(weights);

end


function rho = material_density(region,P)
%MATERIAL_DENSITY Material-density vector.

rho = zeros(size(region));

rho(region == 1) = P.rho_cell;
rho(region == 2) = P.rho_pcm;
rho(region == 3) = P.rho_case;

end


function hSpecific = specific_enthalpy(T,region,P)
%SPECIFIC_ENTHALPY Specific enthalpy relative to 0°C [J/kg].

Tref = 273.15;

hSpecific = zeros(size(T));

cellNodes = region == 1;
caseNodes = region == 3;
pcmNodes = region == 2;

hSpecific(cellNodes) = ...
    P.cp_cell*(T(cellNodes)-Tref);

hSpecific(caseNodes) = ...
    P.cp_case*(T(caseNodes)-Tref);

deltaTm = P.Tm_liquid-P.Tm_solid;

cpMushy = 0.5*(P.cp_pcm_solid+P.cp_pcm_liquid) ...
          +P.L_pcm/deltaTm;

pcmIndices = find(pcmNodes);

for j = 1:numel(pcmIndices)

    i = pcmIndices(j);

    if T(i) <= P.Tm_solid

        hSpecific(i) = ...
            P.cp_pcm_solid*(T(i)-Tref);

    elseif T(i) < P.Tm_liquid

        hSpecific(i) = ...
            P.cp_pcm_solid*(P.Tm_solid-Tref) ...
            +cpMushy*(T(i)-P.Tm_solid);

    else

        hAtLiquidus = ...
            P.cp_pcm_solid*(P.Tm_solid-Tref) ...
            +cpMushy*deltaTm;

        hSpecific(i) = ...
            hAtLiquidus ...
            +P.cp_pcm_liquid*(T(i)-P.Tm_liquid);
    end
end

end