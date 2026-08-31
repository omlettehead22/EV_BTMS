function summaryTable = summarise_scenario_metrics(resultsStruct)
%SUMMARISE_SCENARIO_METRICS
% Calculate thermal, PCM, auxiliary-power and energy-balance metrics.
%
% Input:
%   resultsStruct - structure array returned by run_all_scenarios
%
% Output:
%   summaryTable  - table containing one row per scenario
%
% Temperature results are converted from K to degC.
% Energy results are reported in kJ.
% Auxiliary electrical energy is reported in kJ and Wh.

%% Validate input

if nargin < 1 || isempty(resultsStruct)
    error('summarise_scenario_metrics:EmptyInput', ...
        'resultsStruct cannot be empty.');
end

if ~isstruct(resultsStruct)
    error('summarise_scenario_metrics:InvalidInput', ...
        'resultsStruct must be a structure array.');
end

nSc = numel(resultsStruct);

%% Scenario descriptors

Scenario       = strings(nSc,1);
ScenarioType   = strings(nSc,1);
CoolingType    = strings(nSc,1);
CoolingLevel   = strings(nSc,1);

%% Temperature metrics

Duration_s             = zeros(nSc,1);
T_initial_C            = zeros(nSc,1);
T_peak_C               = zeros(nSc,1);
TimeToPeak_s           = zeros(nSc,1);
T_end_C                = zeros(nSc,1);
TemperatureRise_C      = zeros(nSc,1);
PeakToEndChange_C      = zeros(nSc,1);
T_mean_C               = zeros(nSc,1);
ThermalDose_Cs         = zeros(nSc,1);

%% Cell-uniformity metrics

MaxCellDifference_C    = zeros(nSc,1);
MeanCellDifference_C   = zeros(nSc,1);

%% Temperature-rate metrics

InitialRate_Cmin       = nan(nSc,1);
MaxHeatingRate_Cmin    = nan(nSc,1);
MaxCoolingRate_Cmin    = nan(nSc,1);

%% PCM metrics

PCM_fraction_peak      = zeros(nSc,1);
PCM_fraction_end       = zeros(nSc,1);
PCM_utilisation        = zeros(nSc,1);

%% Auxiliary-energy metrics

P_aux_W                = zeros(nSc,1);
E_aux_kJ               = zeros(nSc,1);
E_aux_Wh               = zeros(nSc,1);

%% Thermal-energy metrics

E_generated_kJ         = zeros(nSc,1);
E_rejected_kJ          = zeros(nSc,1);
E_stored_kJ            = zeros(nSc,1);

E_cell_kJ              = nan(nSc,1);
E_PCM_kJ               = nan(nSc,1);
E_case_kJ              = nan(nSc,1);

HeatRejected_pct       = nan(nSc,1);
EnergyStored_pct       = nan(nSc,1);

BalanceResidual_J      = zeros(nSc,1);
CalculatedResidual_J   = zeros(nSc,1);
BalanceError_pct       = zeros(nSc,1);
BalancePass_0p1pct     = false(nSc,1);

StorageComponentError_J = nan(nSc,1);

%% Temperature-threshold metrics

Threshold40_reached    = false(nSc,1);
TimeTo40C_s            = nan(nSc,1);
SafetyMargin40_C       = zeros(nSc,1);

%% Process every scenario

for k = 1:nSc

    %% Validate scenario-level structure

    requiredScenarioFields = { ...
        'name','type','bcType','hLevel','outputs'};

    missingScenarioFields = requiredScenarioFields( ...
        ~isfield(resultsStruct(k),requiredScenarioFields));

    if ~isempty(missingScenarioFields)
        error('summarise_scenario_metrics:MissingScenarioField', ...
            'Scenario %d is missing: %s', ...
            k,strjoin(missingScenarioFields,', '));
    end

    Scenario(k)       = string(resultsStruct(k).name);
    ScenarioType(k)   = string(resultsStruct(k).type);
    CoolingType(k)    = string(resultsStruct(k).bcType);
    CoolingLevel(k)   = string(resultsStruct(k).hLevel);

    res = resultsStruct(k).outputs;

    %% Validate solver outputs

    requiredOutputFields = { ...
        't', ...
        'Tmax', ...
        'dTmax', ...
        'phi_pcm', ...
        'P_aux', ...
        'E_aux', ...
        'E_generated', ...
        'E_rejected', ...
        'E_stored', ...
        'E_balance_residual', ...
        'balance_error_pct', ...
        'dE_pcm'};

    missingOutputFields = requiredOutputFields( ...
        ~isfield(res,requiredOutputFields));

    if ~isempty(missingOutputFields)
        error('summarise_scenario_metrics:MissingOutputField', ...
            'Scenario "%s" is missing solver outputs: %s', ...
            Scenario(k),strjoin(missingOutputFields,', '));
    end

    %% Extract time histories

    t       = res.t(:);
    T       = res.Tmax(:)-273.15;
    dTcell  = res.dTmax(:);
    phiPCM  = res.phi_pcm(:);

    if numel(t) ~= numel(T)
        error('summarise_scenario_metrics:TemperatureLength', ...
            ['The time and Tmax vectors have different lengths ', ...
             'for scenario "%s".'],Scenario(k));
    end

    if numel(t) ~= numel(dTcell)
        error('summarise_scenario_metrics:DifferenceLength', ...
            ['The time and dTmax vectors have different lengths ', ...
             'for scenario "%s".'],Scenario(k));
    end

    if numel(t) ~= numel(phiPCM)
        error('summarise_scenario_metrics:PCMLength', ...
            ['The time and phi_pcm vectors have different lengths ', ...
             'for scenario "%s".'],Scenario(k));
    end

    if any(~isfinite(t)) || any(~isfinite(T))
        error('summarise_scenario_metrics:NonFiniteData', ...
            'Non-finite time or temperature data found in "%s".', ...
            Scenario(k));
    end

    if any(diff(t) <= 0)
        error('summarise_scenario_metrics:InvalidTime', ...
            'Time must increase strictly in scenario "%s".', ...
            Scenario(k));
    end

    if any(phiPCM < -1e-9) || any(phiPCM > 1+1e-9)
        warning('summarise_scenario_metrics:PCMRange', ...
            ['PCM fraction is outside the expected range 0-1 ', ...
             'for scenario "%s".'],Scenario(k));
    end

    %% Event duration

    Duration_s(k) = t(end)-t(1);

    %% Temperature results

    T_initial_C(k) = T(1);

    [T_peak_C(k),peakIndex] = max(T);
    TimeToPeak_s(k) = t(peakIndex);

    T_end_C(k) = T(end);

    TemperatureRise_C(k) = ...
        T_peak_C(k)-T_initial_C(k);

    PeakToEndChange_C(k) = ...
        T_end_C(k)-T_peak_C(k);

    if Duration_s(k) > 0
        T_mean_C(k) = ...
            trapz(t,T)/Duration_s(k);
    else
        T_mean_C(k) = T(1);
    end

    % Temperature exposure above the event's initial temperature.
    ThermalDose_Cs(k) = ...
        trapz(t,max(T-T_initial_C(k),0));

    %% Cell temperature uniformity

    MaxCellDifference_C(k) = max(dTcell);

    if Duration_s(k) > 0
        MeanCellDifference_C(k) = ...
            trapz(t,dTcell)/Duration_s(k);
    else
        MeanCellDifference_C(k) = dTcell(1);
    end

    %% Temperature rates

    if numel(t) >= 2

        temperatureRate = gradient(T,t)*60;

        MaxHeatingRate_Cmin(k) = ...
            max(temperatureRate);

        MaxCoolingRate_Cmin(k) = ...
            min(temperatureRate);

        % Linear fit across the first 10% of time points.
        nInitial = max(2,round(0.10*numel(t)));
        nInitial = min(nInitial,numel(t));

        initialFit = polyfit( ...
            t(1:nInitial),T(1:nInitial),1);

        InitialRate_Cmin(k) = initialFit(1)*60;
    end

    %% PCM metrics

    PCM_fraction_peak(k) = max(phiPCM);
    PCM_fraction_end(k)  = phiPCM(end);

    if Duration_s(k) > 0
        PCM_utilisation(k) = ...
            trapz(t,phiPCM)/Duration_s(k);
    else
        PCM_utilisation(k) = phiPCM(1);
    end

    %% Auxiliary power and energy

    if isscalar(res.P_aux)

        P_aux_W(k) = res.P_aux;

    else

        PauxVector = res.P_aux(:);

        if numel(PauxVector) == numel(t) && Duration_s(k) > 0
            P_aux_W(k) = ...
                trapz(t,PauxVector)/Duration_s(k);
        else
            P_aux_W(k) = mean(PauxVector);
        end
    end

    E_aux_kJ(k) = res.E_aux/1000;
    E_aux_Wh(k) = res.E_aux/3600;

    %% Event thermal-energy totals

    E_generated_kJ(k) = res.E_generated/1000;
    E_rejected_kJ(k)  = res.E_rejected/1000;
    E_stored_kJ(k)    = res.E_stored/1000;

    E_PCM_kJ(k) = sum(res.dE_pcm(:))/1000;

    if isfield(res,'dE_cell')
        E_cell_kJ(k) = sum(res.dE_cell(:))/1000;
    end

    if isfield(res,'dE_case')
        E_case_kJ(k) = sum(res.dE_case(:))/1000;
    end

    %% Energy distribution

    if abs(res.E_generated) > eps

        HeatRejected_pct(k) = ...
            100*res.E_rejected/res.E_generated;

        EnergyStored_pct(k) = ...
            100*res.E_stored/res.E_generated;
    end

    %% Energy-balance checks

    BalanceResidual_J(k) = ...
        res.E_balance_residual;

    CalculatedResidual_J(k) = ...
        res.E_generated-res.E_rejected-res.E_stored;

    BalanceError_pct(k) = ...
        res.balance_error_pct;

    BalancePass_0p1pct(k) = ...
        BalanceError_pct(k) <= 0.1;

    % Check that the component energies equal total stored energy.
    if isfinite(E_cell_kJ(k)) && ...
       isfinite(E_PCM_kJ(k)) && ...
       isfinite(E_case_kJ(k))

        StorageComponentError_J(k) = ...
            res.E_stored ...
            -1000*(E_cell_kJ(k)+E_PCM_kJ(k)+E_case_kJ(k));
    end

    %% Temperature-threshold check

    thresholdIndex = find(T >= 40,1,'first');

    if ~isempty(thresholdIndex)

        Threshold40_reached(k) = true;

        if thresholdIndex == 1

            TimeTo40C_s(k) = t(1);

        else

            T1 = T(thresholdIndex-1);
            T2 = T(thresholdIndex);

            t1 = t(thresholdIndex-1);
            t2 = t(thresholdIndex);

            if abs(T2-T1) > eps

                % Linear interpolation gives a more precise threshold time.
                TimeTo40C_s(k) = ...
                    t1+(40-T1)*(t2-t1)/(T2-T1);

            else

                TimeTo40C_s(k) = t(thresholdIndex);
            end
        end
    end

    SafetyMargin40_C(k) = 40-T_peak_C(k);

    %% Physical-consistency warnings

    if E_rejected_kJ(k) < -1e-9
        warning('summarise_scenario_metrics:NegativeHeatRejection', ...
            ['Scenario "%s" produced negative rejected energy. ', ...
             'Check the boundary heat-flow sign convention.'], ...
             Scenario(k));
    end

    if BalanceError_pct(k) > 0.1
        warning('summarise_scenario_metrics:EnergyBalance', ...
            ['Scenario "%s" has an energy-balance error of ', ...
             '%.6f%%, exceeding the 0.1%% reporting criterion.'], ...
             Scenario(k),BalanceError_pct(k));
    end

    if abs(BalanceResidual_J(k)-CalculatedResidual_J(k)) > 1e-6
        warning('summarise_scenario_metrics:ResidualMismatch', ...
            ['Stored and independently calculated energy residuals ', ...
             'do not match for scenario "%s".'],Scenario(k));
    end
end

%% Construct summary table

summaryTable = table( ...
    Scenario, ...
    ScenarioType, ...
    CoolingType, ...
    CoolingLevel, ...
    Duration_s, ...
    T_initial_C, ...
    T_peak_C, ...
    TimeToPeak_s, ...
    T_end_C, ...
    TemperatureRise_C, ...
    PeakToEndChange_C, ...
    T_mean_C, ...
    ThermalDose_Cs, ...
    MaxCellDifference_C, ...
    MeanCellDifference_C, ...
    InitialRate_Cmin, ...
    MaxHeatingRate_Cmin, ...
    MaxCoolingRate_Cmin, ...
    PCM_fraction_peak, ...
    PCM_fraction_end, ...
    PCM_utilisation, ...
    P_aux_W, ...
    E_aux_kJ, ...
    E_aux_Wh, ...
    E_generated_kJ, ...
    E_rejected_kJ, ...
    E_stored_kJ, ...
    E_cell_kJ, ...
    E_PCM_kJ, ...
    E_case_kJ, ...
    HeatRejected_pct, ...
    EnergyStored_pct, ...
    BalanceResidual_J, ...
    CalculatedResidual_J, ...
    BalanceError_pct, ...
    BalancePass_0p1pct, ...
    StorageComponentError_J, ...
    Threshold40_reached, ...
    TimeTo40C_s, ...
    SafetyMargin40_C);

end