function [P_aux,E_aux] = aux_power(...
    P,bcType,hLevel,t_vec)
%AUX_POWER Assumed fan/pump power and event energy.

switch lower(bcType)

    case 'air'
        switch lower(hLevel)
            case 'low'
                P_aux = P.P_fan_low;
            case 'mid'
                P_aux = P.P_fan_mid;
            case 'high'
                P_aux = P.P_fan_high;
            otherwise
                error('aux_power:UnknownAirLevel',...
                    'Unknown air-cooling level: %s',hLevel);
        end

    case 'liquid'
        switch lower(hLevel)
            case 'low'
                P_aux = P.P_pump_low;
            case 'mid'
                P_aux = P.P_pump_mid;
            case 'high'
                P_aux = P.P_pump_high;
            otherwise
                error('aux_power:UnknownLiquidLevel',...
                    'Unknown liquid-cooling level: %s',hLevel);
        end

    case {'adiabatic','none'}
        P_aux = 0;

    otherwise
        error('aux_power:UnknownCoolingType',...
            'Unknown cooling type: %s',bcType);
end

if numel(t_vec) < 2
    E_aux = 0;
else
    E_aux = P_aux*(t_vec(end)-t_vec(1));
end

end