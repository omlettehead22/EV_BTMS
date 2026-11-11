function sensitivity_time_pcm()
%SENSITIVITY_TIME_PCM  Sensitivity of Tmax and PCM melting to event duration.
%
% Fixes ambient/coolant temperature and varies total event duration t_end.
% Uses the same RT31-type PCM and BTMS parameters as params_materials.m.

    %% 1. Load parameters and choose scenario/BTMS
    P = params_materials();

    % Constant environment: use coolant temperature for liquid case,
    % or ambient air for air case (you can switch).
    T_env = P.T_coolant;  % K

    % Choose scenario and BTMS configuration to study
    scenarioType = 'charge';  % 'drive' or 'charge'
    bcType       = 'liquid';  % 'air' or 'liquid'
    hLevel       = 'mid';     % 'low', 'mid', 'high'

    % Durations to sweep [s]
    durations = [900, 1800, 2700, 3600];

    % Temperature threshold for "limit" [°C]
    T_threshold_C = 40;

    %% 2. Allocate storage for sensitivity metrics
    nCases   = numel(durations);
    T_peak_C = zeros(nCases,1);   % peak Tmax in °C
    T_end_C  = zeros(nCases,1);   % end-of-event Tmax in °C
    phi_end  = zeros(nCases,1);   % PCM liquid fraction at end
    t_cross  = nan(nCases,1);     % time when Tmax first exceeds threshold

    %% 3. Plot Tmax(t) curves for each duration
    figure; hold on;
    colors = lines(nCases);

    for k = 1:nCases
        t_end = durations(k);

        % Run scenario with overridden duration
        res = run_scenario_1D(P, scenarioType, bcType, hLevel, T_env, t_end);

        % Convert Tmax to °C
        T_C = res.Tmax - 273.15;

        % Plot Tmax vs time
        plot(res.t, T_C, 'Color', colors(k,:), ...
            'DisplayName', sprintf('t_{end} = %d s', t_end));

        % Sensitivity metrics
        T_peak_C(k) = max(T_C);
        T_end_C(k)  = T_C(end);
        phi_end(k)  = res.phi_pcm(end);

        idx = find(T_C >= T_threshold_C, 1, 'first');
        if ~isempty(idx)
            t_cross(k) = res.t(idx);
        end
    end

    xlabel('Time [s]');
    ylabel('Max cell temperature [°C]');
    title(sprintf('T_{max}(t) for %s-%s-%s at constant ambient', ...
          scenarioType, bcType, hLevel));
    legend('Location','best');
    grid on;

    %% 4. Summary plots vs duration
    figure;

    subplot(3,1,1);
    plot(durations, T_peak_C, 'o-');
    xlabel('Event duration t_{end} [s]');
    ylabel('Peak T_{max} [°C]');
    title('Peak cell temperature vs event duration');
    grid on;

    subplot(3,1,2);
    plot(durations, T_end_C, 'o-');
    xlabel('Event duration t_{end} [s]');
    ylabel('End-of-event T_{max} [°C]');
    title('Final cell temperature vs event duration');
    grid on;

    subplot(3,1,3);
    plot(durations, phi_end, 'o-');
    xlabel('Event duration t_{end} [s]');
    ylabel('Final PCM liquid fraction [-]');
    title('PCM melting state vs event duration');
    grid on;

    %% 5. Print threshold-crossing times
    fprintf('\nSensitivity summary for %s-%s-%s at T_env = %.1f °C:\n', ...
        scenarioType, bcType, hLevel, T_env - 273.15);
    for k = 1:nCases
        if isnan(t_cross(k))
            fprintf('  t_end = %4d s: peak T = %.2f °C, phi_end = %.2f, threshold NOT reached.\n', ...
                durations(k), T_peak_C(k), phi_end(k));
        else
            fprintf('  t_end = %4d s: peak T = %.2f °C, phi_end = %.2f, threshold reached at t = %.1f s.\n', ...
                durations(k), T_peak_C(k), phi_end(k), t_cross(k));
        end
    end
end